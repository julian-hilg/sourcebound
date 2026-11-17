# Referee report (draft mode): example_study

Referee agent, 2026-11-09. Recommendation: minor revision.

| Criterion | Score | Reason |
| --- | --- | --- |
| Question and contribution | 3 | well-known fact; value is the clean, reproducible quantification |
| Identification | 4 | descriptive question, tests match the hypotheses |
| Data quality and provenance | 5 | official series, raw archive, snapshot ids |
| Statistical validity | 4 | block bootstrap respects dependence; binomial test ignores clustering |
| Robustness | 3 | no subperiods, no other pairs |
| Interpretation | 4 | conclusions match the evidence |
| Relation to literature | 3 | one reference; add GARCH-based evidence if extended |
| Clarity | 4 | short and clear |
| Reproducibility | 5 | every number recorded with provenance |

Major points
1. The binomial test assumes independent days; volatility clustering makes extreme days
   cluster, which overstates significance. Report a block-bootstrap p-value as robustness.

Minor points
1. Add subperiod results (before/after 2008) as exploratory robustness.
2. State in the abstract that standardisation uses the full-sample standard deviation.
