"""Data contracts: one YAML file per table, the single description of a dataset.

Location:  <data root>/registry/contracts/<schema>/<table>.yaml   shared domains (market, retail, geo, ...)
           <hub>/contracts/<schema>/<table>.yaml      examples and fallback
           <project>/contracts/<schema>/<table>.yaml  project tables (schema proj_<slug>)

    name: market.ecb_fx_daily
    title: ECB euro reference exchange rates
    description: ...
    owner: hub                       # or a project slug
    grain: one row per date and currency
    primary_key: [date, currency]
    license: ...
    sources: [ecb_data_portal]       # ids in the source register (registry/datasources/)
    pipeline: pipelines/ecb_fx
    columns:
      date:     {type: date, description: Reference date}
      currency: {type: string, pattern: "^[A-Z]{3}$"}
      rate:     {type: double, unit: CUR per EUR, min: 0}

The same file drives validation (lake.write), table comments in the catalog,
the data appendix of the paper (sb lineage) and the Frictionless
datapackage.json that ships with published data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
import yaml

TYPES = {
    "string": pl.Utf8, "int": pl.Int64, "double": pl.Float64, "bool": pl.Boolean,
    "date": pl.Date, "timestamp": pl.Datetime("us", "UTC"), "datetime": pl.Datetime("us"),
}
FRICTIONLESS = {"string": "string", "int": "integer", "double": "number", "bool": "boolean",
                "date": "date", "timestamp": "datetime", "datetime": "datetime"}


@dataclass
class Contract:
    name: str
    columns: dict[str, dict]
    title: str = ""
    description: str = ""
    owner: str = "hub"
    grain: str = ""
    primary_key: list[str] = field(default_factory=list)
    license: str = ""
    sources: list[str] = field(default_factory=list)
    pipeline: str = ""
    extra_columns: str = "forbid"       # or "allow"
    path: Path | None = None

    @classmethod
    def load(cls, path: Path) -> "Contract":
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d and k != "path"}
        for col, spec in known["columns"].items():
            if spec.get("type") not in TYPES:
                raise ValueError(f"{path}: column {col}: unknown type {spec.get('type')!r} "
                                 f"(use one of {', '.join(TYPES)})")
        return cls(**known, path=path)

    @property
    def schema(self) -> dict[str, pl.DataType]:
        return {c: TYPES[s["type"]] for c, s in self.columns.items()}

    # ------------------------------------------------------------------ validation
    def conform(self, df: pl.DataFrame) -> pl.DataFrame:
        """Cast to contract types and order (strict: impossible casts raise)."""
        cols = [pl.col(c).cast(t, strict=True) for c, t in self.schema.items() if c in df.columns]
        out = df.with_columns(cols)
        extra = [c for c in df.columns if c not in self.columns]
        return out.select([*[c for c in self.columns if c in out.columns], *extra])

    def validate(self, df: pl.DataFrame) -> list[str]:
        """List of human-readable violations (empty = valid)."""
        errs: list[str] = []
        missing = [c for c in self.columns if c not in df.columns]
        if missing:
            errs.append(f"missing columns: {missing}")
        extra = [c for c in df.columns if c not in self.columns]
        if extra and self.extra_columns != "allow":
            errs.append(f"columns not in contract: {extra} (add them to {self.path})")
        try:
            df = self.conform(df)
        except Exception as e:  # noqa: BLE001 -- report, do not crash
            return errs + [f"type cast failed: {e}"]
        for c, spec in self.columns.items():
            if c not in df.columns:
                continue
            s = df[c]
            if not spec.get("nullable", True) or c in self.primary_key:
                n = s.null_count()
                if n:
                    errs.append(f"{c}: {n} null values (not nullable)")
            if "min" in spec and (s < spec["min"]).any():
                errs.append(f"{c}: values below min {spec['min']}")
            if "max" in spec and (s > spec["max"]).any():
                errs.append(f"{c}: values above max {spec['max']}")
            if "enum" in spec:
                bad = set(s.drop_nulls().unique().to_list()) - set(spec["enum"])
                if bad:
                    errs.append(f"{c}: values outside enum: {sorted(map(str, bad))[:5]}")
            if "pattern" in spec:
                rx = re.compile(spec["pattern"])
                bad = [v for v in s.drop_nulls().unique().to_list() if not rx.search(str(v))]
                if bad:
                    errs.append(f"{c}: {len(bad)} values do not match {spec['pattern']}: {bad[:3]}")
        if self.primary_key and not missing:
            dup = df.select(self.primary_key).is_duplicated().sum()
            if dup:
                errs.append(f"primary key {self.primary_key}: {dup} duplicated rows")
        return errs

    # ------------------------------------------------------------------ export
    def datapackage_resource(self, path: str, sha256: str | None = None, rows: int | None = None) -> dict:
        res = {
            "name": self.name.replace(".", "__"),
            "title": self.title, "description": self.description.strip(),
            "path": path, "format": "parquet", "mediatype": "application/vnd.apache.parquet",
            "schema": {
                "fields": [{"name": c, "type": FRICTIONLESS[s["type"]],
                            **({"description": s["description"]} if "description" in s else {}),
                            **({"unit": s["unit"]} if "unit" in s else {})}
                           for c, s in self.columns.items()],
                **({"primaryKey": self.primary_key} if self.primary_key else {}),
            },
            "sources": [{"title": s} for s in self.sources],
            "licenses": [{"title": self.license}] if self.license else [],
        }
        if sha256:
            res["hash"] = f"sha256:{sha256}"
        if rows is not None:
            res["rows"] = rows
        return res


def find(table: str, *, hub_root: Path | None = None, project_root: Path | None = None,
         registry: Path | None = None) -> Contract | None:
    """Contract for 'schema.table': project contracts, then the registry, then the hub's copies."""
    schema, name = table.split(".", 1)
    for base in (project_root, registry, hub_root):
        if base is not None:
            p = base / "contracts" / schema / f"{name}.yaml"
            if p.exists():
                return Contract.load(p)
    return None


def all_contracts(base: Path) -> list[Contract]:
    return [Contract.load(p) for p in sorted((base / "contracts").glob("*/*.yaml"))]
