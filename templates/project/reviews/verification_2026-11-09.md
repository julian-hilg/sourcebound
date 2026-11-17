# Verification report: deliverables/paper (main.tex, sections/)

Verifier agent, 2026-11-09. Statements checked: 9. Supported 8, partly supported 1
(fixed), unsupported 0, no evidence 0.

| # | Statement (short) | Location | Evidence | Verdict | Note |
| --- | --- | --- | --- | --- | --- |
| 1 | Heavy tails are a documented stylised fact | Sec. 1 | Cont2001EmpiricalProperties, Sec. 2 | supported | |
| 2 | ECB publishes reference rates every working day | Sec. 2 | W-0001 (archived page) | partly supported | page: "every working day, except on TARGET closing days"; text amended |
| 3 | Sample size, start and end date | Abstract, Sec. 2 | R:data.n_days, R:data.start, R:data.end | supported | |
| 4 | Daily volatility | Sec. 2 | R:data.vol_daily | supported | |
| 5 | Excess kurtosis and interval | Abstract, Sec. 4 | R:h1.kurtosis, R:h1.kurtosis_lo, R:h1.kurtosis_hi | supported | |
| 6 | Count and share of 3-sigma days | Sec. 4 | R:h2.count, R:h2.share, R:h2.share_normal | supported | |
| 7 | p-value of binomial test | Sec. 4 | R:h2.pvalue | supported | |
| 8 | Factor relative to normal | Abstract, Sec. 5 | R:h2.ratio | supported | |
| 9 | Volatility clustering explains part of the fat tails | Sec. 5 | none in ledger | supported as limitation | phrased as a caveat, not a finding; add a citation if expanded |

Fixes needed: none open.
