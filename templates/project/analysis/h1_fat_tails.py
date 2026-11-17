"""H1 + H2: fat tails of daily EUR/USD returns (tests exactly as in hypotheses.yaml).

Run from the project root:  make analysis   (or: <hub>/.venv/bin/python analysis/h1_fat_tails.py)
Records every number via sourcebound.results; writes tables and figure data.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from sourcebound import lake, results, tables

ROOT = Path(__file__).resolve().parents[1]
rng = np.random.default_rng(1)

# ---------------------------------------------------------------- data
fx = (lake.read("market.ecb_fx_daily", where="currency = 'USD'")
        .sort("date")
        .with_columns(pl.col("rate").log().diff().alias("r"))
        .drop_nulls("r"))
r = fx["r"].to_numpy()
n = len(r)
results.record("data.n_days", n, fmt="int")
results.record("data.start", fx["date"].min().isoformat())
results.record("data.end", fx["date"].max().isoformat())
results.record("data.vol_daily", r.std(ddof=1), fmt="pct2", note="standard deviation of daily log returns")

# ---------------------------------------------------------------- H1: excess kurtosis, block bootstrap
def block_bootstrap(x: np.ndarray, stat, block: int = 20, reps: int = 2000) -> np.ndarray:
    nb = int(np.ceil(len(x) / block))
    starts = rng.integers(0, len(x) - block, size=(reps, nb))
    idx = (starts[:, :, None] + np.arange(block)).reshape(reps, -1)[:, : len(x)]
    return np.array([stat(x[i]) for i in idx])


kurt = stats.kurtosis(r, fisher=True, bias=False)
boot = block_bootstrap(r, lambda x: stats.kurtosis(x, fisher=True, bias=False))
lo, hi = np.percentile(boot, [2.5, 97.5])
results.record("h1.kurtosis", kurt, fmt="{:.2f}", hypothesis="H1", ci=(lo, hi))
results.record("h1.kurtosis_lo", lo, fmt="{:.2f}", hypothesis="H1")
results.record("h1.kurtosis_hi", hi, fmt="{:.2f}", hypothesis="H1")
results.record("h1.decision", "supported" if lo > 0 else "refuted" if hi < 0 else "inconclusive",
               hypothesis="H1")

# ---------------------------------------------------------------- H2: frequency of |z| > 3
z = (r - r.mean()) / r.std(ddof=1)
k = int((np.abs(z) > 3).sum())
p_norm = 2 * stats.norm.sf(3)
test = stats.binomtest(k, n, p_norm, alternative="greater")
results.record("h2.count", k, fmt="int", hypothesis="H2")
results.record("h2.share", k / n, fmt="pct2", hypothesis="H2")
results.record("h2.share_normal", p_norm, fmt="pct2", hypothesis="H2")
results.record("h2.ratio", (k / n) / p_norm, fmt="{:.1f}", hypothesis="H2")
results.record("h2.pvalue", test.pvalue, fmt="sci1", hypothesis="H2")

# ---------------------------------------------------------------- outputs for tables and figures
tables.from_rows(
    ROOT / "tables" / "h1_summary.tex",
    header=["", "Mean (%)", "SD (%)", "Skewness", "Excess kurtosis", "Min (%)", "Max (%)"],
    rows=[["EUR/USD", 100 * r.mean(), 100 * r.std(ddof=1), stats.skew(r), kurt, 100 * r.min(), 100 * r.max()]],
    decimals=[0, 3, 2, 2, 2, 2, 2])
tables.from_rows(
    ROOT / "tables" / "h2_tails.tex",
    header=["Threshold", "Observed days", "Observed share (%)", "Normal share (%)", "Ratio"],
    rows=[[f"$|z| > {t}$", int((np.abs(z) > t).sum()), 100 * (np.abs(z) > t).mean(),
           100 * 2 * stats.norm.sf(t), (np.abs(z) > t).mean() / (2 * stats.norm.sf(t))] for t in (2, 3, 4)],
    decimals=[0, 0, 2, 2, 1])
fx.select("date", "r").with_columns(z=pl.Series(z)).write_parquet(ROOT / "results" / "h1_returns.parquet")
print(f"H1 kurtosis {kurt:.2f} [{lo:.2f}, {hi:.2f}];  H2 {k} days |z|>3, ratio {(k / n) / p_norm:.1f}, p={test.pvalue:.1e}")
