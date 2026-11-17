# Landscape

Synthesis by the lead from `research/notes/` (scout notes). Every statement points to a
claim in `evidence/claims.yaml`.

## What is known

- Daily returns of liquid financial assets have heavier tails than the normal distribution;
  this is one of the best-documented stylised facts [C001].
- The ECB publishes euro reference rates every working day (except TARGET closing days),
  based on a concertation around 14:10 CET; the series starts in 1999, which gives a long
  and consistent sample [C002; start date from `data:market.ecb_fx_daily`].

## Gaps this study fills

A simple, reproducible quantification for EUR/USD with the official reference rate series,
expressed as the frequency of large moves relative to a normal model (C003, open before
the analysis, decided by H2).

## Candidate hypotheses

See `hypotheses.yaml` (H1 kurtosis, H2 frequency of 3-sigma days).
