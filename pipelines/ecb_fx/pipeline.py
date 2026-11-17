"""ECB reference rates -> market.ecb_fx_daily   (shared pipeline, reference implementation)

    python pipelines/ecb_fx/pipeline.py                      # incremental: since last date
    python pipelines/ecb_fx/pipeline.py --start 1999-01-01   # backfill
    python pipelines/ecb_fx/pipeline.py --reparse            # rebuild the table from raw only

Pattern for every pipeline:  fetch (archived, polite)  ->  parse (pure function, tested
on fixtures)  ->  validate against the contract  ->  upsert into the lake.
"""
from __future__ import annotations

import argparse
import io
from datetime import date, timedelta

import polars as pl

from sourcebound import lake
from sourcebound.fetch import Fetcher, read_raw

SOURCE = "ecb_data_portal"
TABLE = "market.ecb_fx_daily"
URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{cur}.EUR.SP00.A"
CURRENCIES = ["USD", "GBP", "CHF", "JPY", "NOK", "SEK", "PLN", "CZK"]


def parse(body: bytes, raw_ref: str) -> pl.DataFrame:
    """SDMX csvdata -> contract columns. Pure: no I/O, so it is tested on fixtures."""
    df = pl.read_csv(io.BytesIO(body), infer_schema_length=0)
    return (df.select(
                pl.col("TIME_PERIOD").str.to_date("%Y-%m-%d").alias("date"),
                pl.col("CURRENCY").alias("currency"),
                pl.col("OBS_VALUE").cast(pl.Float64, strict=False).alias("rate"),
                pl.col("OBS_STATUS").alias("obs_status"))
              .filter(pl.col("rate").is_not_null() & pl.col("rate").is_finite())
              .with_columns(pl.lit(raw_ref).alias("raw_ref"))
              .sort("date", "currency"))


def last_date() -> date | None:
    try:
        return lake.sql(f"SELECT max(date) AS d FROM {TABLE}")["d"][0]
    except Exception:  # table does not exist yet
        return None


def run(start: str | None = None) -> int:
    since = date.fromisoformat(start) if start else (last_date() or date(1999, 1, 1)) - timedelta(days=7)
    f = Fetcher(SOURCE, timeout=180)
    resp, ref = f.get(URL.format(cur="+".join(CURRENCIES)),
                      params={"format": "csvdata", "startPeriod": since.isoformat()})
    df = parse(resp.content, ref.sha256)
    snap = lake.write(df, TABLE, mode="upsert", note=f"ECB EXR since {since}")
    print(f"{TABLE}: {len(df)} rows upserted (snapshot {snap}, raw {ref.path})")
    return snap


def reparse() -> int:
    """Rebuild the table from the raw archive only -- proves the table is reproducible."""
    f = Fetcher(SOURCE)
    frames = [parse(read_raw(SOURCE, m["sha256"]), m["sha256"])
              for m in f.manifest() if m.get("sha256") and m["status"] == 200]
    df = pl.concat(frames).unique(["date", "currency"], keep="last").sort("date", "currency")
    return lake.write(df, TABLE, mode="replace", note="rebuilt from raw archive")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--reparse", action="store_true")
    a = ap.parse_args()
    reparse() if a.reparse else run(a.start)
