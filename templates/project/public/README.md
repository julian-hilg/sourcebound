# Example Study: Fat Tails in Daily EUR/USD Returns

**Paper:** [`example_study.pdf`](example_study.pdf)

Daily EUR/USD returns are fat-tailed: large moves occur several times as often as a normal
distribution implies. Both hypotheses were pre-registered (`hypotheses.yaml`); every number
in the paper is recorded with its provenance in `results/results.json`.

## Reproduce

```sh
uv sync                                   # Python environment (pyproject.toml)
# download the data listed in data/manifest.json into data/ and check the sha256
uv run python analysis/h1_fat_tails.py    # recomputes results/results.json and tables
uv run python figures/make_figures.py
```

## Contents

| Path | Content |
| --- | --- |
| `analysis/` | analysis scripts, one per hypothesis |
| `pipelines/`, `contracts/` | data pipelines and data contracts |
| `results/results.json` | every reported number with script, git commit and data snapshot |
| `hypotheses.yaml` | pre-registered hypotheses and decisions |
| `evidence/` | claim ledger and web sources |
| `figures/`, `tables/` | figures (PDF) and tables (CSV) |
| `data/` | data manifest (files hosted outside git) |

Built with Sourcebound.

## Licence

Code: MIT. Paper, figures and tables: CC BY 4.0. Data: see the licence of each source in
`data/manifest.json` and `contracts/`.
