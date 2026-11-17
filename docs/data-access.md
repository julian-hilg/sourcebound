# Reading the research lake from anywhere

The lake is a DuckLake: Parquet files (`data_path`) plus a SQL catalog (`catalog` in
`hub.toml` or the user configuration; `sb doctor` prints the resolved values). Every client that runs DuckDB with the `ducklake` extension sees the same
tables, snapshots and history. Writes go through `sourcebound.lake.write` (contracts are
enforced there); apps should read only.

## Python (research code)

```python
from sourcebound import lake
fx = lake.read("market.ecb_fx_daily", where="currency = 'USD'")   # polars
old = lake.read("market.ecb_fx_daily", as_of=12)                   # snapshot 12
lake.sql("SELECT currency, avg(rate) FROM market.ecb_fx_daily GROUP BY 1")
```

## DuckDB CLI or any DuckDB client (Node, Rust, Go, Java, R)

```sql
INSTALL ducklake; LOAD ducklake;
ATTACH 'ducklake:sqlite:/path/to/research-lake/catalog.sqlite' AS lake
  (DATA_PATH '/path/to/research-lake/data/', READ_ONLY);
USE lake;
SELECT * FROM market.ecb_fx_daily ORDER BY date DESC LIMIT 5;
SELECT * FROM lake.snapshots();                     -- history with commit messages
SELECT * FROM market.ecb_fx_daily AT (VERSION => 12);
```

Node.js (`@duckdb/node-api`): run the same three statements on a connection; the result
is the same table. Keep one long-lived connection per process.

## Web apps and several machines: Postgres catalog

A SQLite catalog serves processes on one machine. For a web app (or a server and a
laptop) move the catalog to Postgres and the Parquet files to object storage:

1. `make db-up` (Postgres 17 on 127.0.0.1:5433, see `compose.yaml`), or a managed Postgres.
2. Optionally create a bucket (Cloudflare R2, S3) and set the credentials in `.env`.
3. In `hub.toml`:
   `catalog = "postgres:dbname=lake host=localhost port=5433 user=lake password=lake"`
   `data_path = "s3://<bucket>/lake/"` (or keep the local folder).
4. Copy existing tables once: attach both catalogs in DuckDB and
   `CREATE TABLE new.<schema>.<table> AS SELECT * FROM old.<schema>.<table>` per table.

The app then attaches the same `ducklake:postgres:...` catalog read-only. Apps that only
speak SQL to Postgres get a serving schema instead: in DuckDB,
`ATTACH 'dbname=lake host=localhost port=5433 user=lake' AS pg (TYPE postgres);
CREATE OR REPLACE TABLE pg.serve.<name> AS SELECT ... FROM lake.<schema>.<table>;`
Refresh it from the pipeline that updates the source table.

## Without DuckLake: plain Parquet

`sb lake export <schema>.<table> <path>.parquet` writes a self-contained file that pandas,
polars, Arrow, Spark, BigQuery or a browser (DuckDB-Wasm) can read. Published data is
exactly this, plus a `datapackage.json` (Frictionless) that documents every column.

## Conventions an app can rely on

- Table names `<schema>.<table>`; column names `snake_case`; dates as `DATE`, timestamps in UTC.
- Every shared table has a contract with types, units, primary key and licence
  (`contracts/<schema>/<table>.yaml`), and `raw_ref` links rows to the archived source bytes.
- Schemas `proj_*` are internal to a study and may change without notice.
