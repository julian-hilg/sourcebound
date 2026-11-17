"""Figures for the deliverable (sourcebound.plot: serif, black, sized to the text width).

Run:  make figures   -- reads results/*.parquet written by the analysis scripts.
Never compute new results here; only draw what the analysis recorded.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from sourcebound import plot as jp

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures"
jp.setup()


def fig_tails():
    d = pl.read_parquet(ROOT / "results" / "h1_returns.parquet")
    z = d["z"].to_numpy()
    fig, (ax1, ax2) = jp.subplots(1, 2, width=1.0, aspect=0.36)
    bins = np.linspace(-6, 6, 97)
    ax1.hist(z, bins=bins, density=True, color="0.75", edgecolor="none", label="EUR/USD")
    x = np.linspace(-6, 6, 400)
    ax1.plot(x, stats.norm.pdf(x), color="black", label="Normal")
    ax1.set_xlabel("Standardised daily return")
    ax1.set_ylabel("Density")
    ax1.legend(loc="upper left")
    t = np.linspace(1, 5, 41)
    ax2.semilogy(t, [(np.abs(z) > s).mean() for s in t], color="black", label="EUR/USD")
    ax2.semilogy(t, 2 * stats.norm.sf(t), color="black", linestyle="--", label="Normal")
    ax2.set_xlabel("Threshold $k$")
    ax2.set_ylabel(r"Share of days with $|z|>k$")
    ax2.legend(loc="lower left")
    jp.save(fig, "fig_tails", outdir=OUT)


if __name__ == "__main__":
    fig_tails()
