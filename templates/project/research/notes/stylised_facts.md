# Are daily FX returns fat-tailed? (stylised facts)
Scout note, 2026-11-09. Budget used: 4 searches, 3 fetches.

## Answer in three sentences
Heavy tails of daily returns are a standard stylised fact across asset classes, including
exchange rates. Cont (2001) lists heavy tails among the stylised facts of returns. Sample
kurtosis reacts strongly to single extreme days, so a bootstrap interval is advisable.

## Findings
| # | Finding | Evidence (ref, loc/quote) | Strength |
| 1 | Unconditional return distributions show heavy tails | Cont2001EmpiricalProperties, Sec. 2, fact 2 | strong |
| 2 | ECB reference rates are updated around 16:00 CET every working day | W-0001, "usually updated at around 16:00 CET every working day, except on TARGET closing days" | strong |

## Contradictions and open points
- Sample kurtosis reacts strongly to single extreme days (own reasoning, not yet sourced;
  the analyst should report a bootstrap interval).

## Proposed claims
- text: "Daily returns of liquid financial assets are heavy-tailed."  kind: literature

## To add to Zotero
- doi:10.1080/713665670 (Cont 2001, stylised facts)
