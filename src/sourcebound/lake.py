"""Data client: one DuckLake catalog over Parquet files, shared by all projects and apps.

    from sourcebound import lake
    df  = lake.read("market.ecb_fx_daily")                    # polars, newest snapshot
    old = lake.read("market.ecb_fx_daily", as_of=12)          # time travel (snapshot id)
    lake.write(df, "market.ecb_fx_daily", mode="upsert", note="ECB daily run")
    con = lake.connect()                                      # raw DuckDB connection, schema `lake`

Naming:   <schema>.<table>
          shared domains (market, retail, geo, macro, ...)  -> contract in the registry REQUIRED
          proj_<slug>                                       -> project-owned, contract recommended
Lineage:  every read() remembers (table, snapshot); results.record() stores it, so each
          number in a deliverable points to the exact data version it came from.
Public:   without a configuration, or in a published bundle, read() falls back to
          ./data/<schema>.<table>.parquet, downloaded from the data manifest.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import polars as pl

from . import config, contracts

READS: dict[str, int | None] = {}       # table -> snapshot id read in this process
_CON: duckdb.DuckDBPyConnection | None = None


def _attach_sql(h: config.Hub, read_only: bool) -> str:
    opts = [f"DATA_PATH '{h.data_path}'"]
    if read_only:
        opts.append("READ_ONLY")
    return f"ATTACH 'ducklake:{h.catalog}' AS lake ({', '.join(opts)})"


def connect(read_only: bool = False, *, fresh: bool = False) -> duckdb.DuckDBPyConnection:
    """DuckDB connection with the lake attached as `lake` (and USE lake)."""
    global _CON
    if _CON is not None and not fresh:
        return _CON
    h = config.hub()
    if h.catalog.startswith("sqlite:") or "://" not in h.data_path:
        Path(h.lake_root).mkdir(parents=True, exist_ok=True)
    if "://" not in h.data_path:
        Path(h.data_path).mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    for ext in ("ducklake", *(["sqlite"] if h.catalog.startswith("sqlite:") else []),
                *(["postgres"] if h.catalog.startswith("postgres:") else []),
                *(["httpfs"] if h.data_path.startswith(("s3://", "r2://", "gs://", "https://")) else [])):
        try:
            con.load_extension(ext)
        except duckdb.Error:
            con.install_extension(ext)      # first use: needs network once
            con.load_extension(ext)
    if h.data_path.startswith(("s3://", "r2://")):
        # credentials from the environment / ~/.aws (R2: AWS_ENDPOINT_URL or a DuckDB secret)
        _run(con, "CREATE OR REPLACE SECRET lake_s3 (TYPE s3, PROVIDER credential_chain)")
    _run(con, _attach_sql(h, read_only))
    _run(con, "USE lake")
    if not fresh:
        _CON = con
    return con


def _run(con: duckdb.DuckDBPyConnection, query: str, params: list | None = None) -> list:
    """Execute and fully consume the result (DuckDB 2 refuses new work while a result is open)."""
    return con.execute(query, params).fetchall() if params else con.execute(query).fetchall()


def _check_name(table: str) -> tuple[str, str]:
    if table.count(".") != 1:
        raise ValueError(f"table must be '<schema>.<table>', got {table!r}")
    return tuple(table.split("."))  # type: ignore[return-value]


def snapshot_id(con: duckdb.DuckDBPyConnection | None = None) -> int:
    con = con or connect()
    return _run(con, "SELECT max(snapshot_id) FROM lake.snapshots()")[0][0]


def tables() -> pl.DataFrame:
    con = connect()
    return con.sql("""SELECT schema_name AS schema, table_name AS "table", estimated_size AS rows_est, comment
                      FROM duckdb_tables() WHERE database_name = 'lake' ORDER BY 1, 2""").pl()


def snapshots(limit: int = 20) -> pl.DataFrame:
    return connect().sql(f"""SELECT snapshot_id, snapshot_time, changes, author, commit_message
                             FROM lake.snapshots() ORDER BY snapshot_id DESC LIMIT {int(limit)}""").pl()


# ---------------------------------------------------------------------------- read
def _public_path(table: str) -> Path | None:
    base = Path(os.environ.get("SB_PUBLIC_DATA", "data"))
    p = base / f"{table}.parquet"
    return p if p.exists() else None


def read(table: str, *, as_of: int | None = None, columns: list[str] | None = None,
         where: str | None = None) -> pl.DataFrame:
    """Read a table as polars. `as_of` = snapshot id (time travel). `where` = SQL predicate."""
    _check_name(table)
    h = config.hub(required=False)
    p = _public_path(table)
    # A published bundle (./data/<table>.parquet) wins over the user-level configuration,
    # so a clone reproduces from its own pinned data even on a machine that has a lake.
    if h is None or (h.source == "user" and p is not None):
        if p is None:
            raise FileNotFoundError(f"no configuration and no ./data/{table}.parquet (see data/README.md)")
        lf = pl.scan_parquet(p)
        if where:
            lf = pl.SQLContext(t=lf).execute(f"SELECT * FROM t WHERE {where}")
        df = lf.collect()
        READS[table] = None
        return df.select(columns) if columns else df
    con = connect()
    snap = as_of if as_of is not None else snapshot_id(con)
    cols = ", ".join(f'"{c}"' for c in columns) if columns else "*"
    sql = f"SELECT {cols} FROM lake.{table} AT (VERSION => {int(snap)})"
    if where:
        sql += f" WHERE {where}"
    df = con.sql(sql).pl()
    READS[table] = snap
    return df


def sql(query: str) -> pl.DataFrame:
    """Ad-hoc SQL against the lake (tables as <schema>.<table>). Not lineage-tracked."""
    return connect().sql(query).pl()


# ---------------------------------------------------------------------------- write
def write(df: pl.DataFrame, table: str, *, mode: str = "append", note: str = "",
          author: str | None = None, validate: bool = True) -> int:
    """Validate against the contract and write. mode: append | upsert | replace.

    Returns the new snapshot id. Shared domains (schema not starting with proj_)
    require a contract; writes are atomic and carry a commit message.
    """
    schema, name = _check_name(table)
    if mode not in {"append", "upsert", "replace"}:
        raise ValueError("mode must be append, upsert or replace")
    h = config.hub()
    p = config.project(required=False)
    c = contracts.find(table, hub_root=h.root, registry=h.registry, project_root=p.root if p else None)
    if c is None and not schema.startswith("proj_"):
        raise ValueError(f"{table}: shared tables need a contract in {h.contracts_dir / schema}/{name}.yaml")
    if c is not None:
        if validate:
            errs = c.validate(df)
            if errs:
                raise ValueError(f"{table} violates its contract:\n  - " + "\n  - ".join(errs))
        df = c.conform(df)
    if mode == "upsert" and not (c and c.primary_key):
        raise ValueError("upsert needs a primary_key in the contract")
    con = connect()
    con.register("_sb_df", df.to_arrow())
    author = author or (p.slug if p else os.environ.get("USER") or os.environ.get("USERNAME", "hub"))
    msg = note or f"{mode} {len(df)} rows"
    try:
        _run(con, "BEGIN TRANSACTION")
        _run(con, f"CREATE SCHEMA IF NOT EXISTS lake.{schema}")
        exists = _run(con, f"""SELECT count(*) FROM duckdb_tables() WHERE database_name='lake'
                               AND schema_name='{schema}' AND table_name='{name}'""")[0][0]
        if mode == "replace" or not exists:
            _run(con, f"CREATE OR REPLACE TABLE lake.{schema}.{name} AS SELECT * FROM _sb_df")
        else:
            if mode == "upsert":
                on = " AND ".join(f't."{k}" = d."{k}"' for k in c.primary_key)  # type: ignore[union-attr]
                _run(con, f"DELETE FROM lake.{schema}.{name} t USING _sb_df d WHERE {on}")
            _run(con, f"INSERT INTO lake.{schema}.{name} BY NAME SELECT * FROM _sb_df")
        if c is not None and c.title:
            title = c.title.replace("'", "''")
            _run(con, f"COMMENT ON TABLE lake.{schema}.{name} IS '{title}'")
        _run(con, "CALL lake.set_commit_message(?, ?, extra_info => ?)",
             [author, f"{table}: {msg}", json.dumps({"rows": len(df), "mode": mode})])
        _run(con, "COMMIT")
    except Exception:
        _run(con, "ROLLBACK")
        raise
    finally:
        con.unregister("_sb_df")
    return snapshot_id(con)


# ---------------------------------------------------------------------------- export
def export(table: str, path: str | Path, *, as_of: int | None = None) -> Path:
    """Plain Parquet copy (zstd) for publication or for tools without DuckLake."""
    df = read(table, as_of=as_of)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression="zstd")
    return path
