# Example Study: Fat Tails in Daily EUR/USD Returns

Project brief for agents. The Sourcebound rules (hub `AGENTS.md`) apply; this file adds what is
specific to this study. The lead keeps it current.

- **Question:** Are daily EUR/USD returns fat-tailed, and how much does a normal
  distribution understate the probability of large moves?
- **Deliverable:** short working paper (`deliverables/paper/main.tex` + `sections/`, English).
- **Phase:** see `project.yaml`; decisions in `log.md`.
- **Data:** shared table `market.ecb_fx_daily` (hub pipeline `pipelines/ecb_fx`). No
  project-owned tables.
- **Scope limits:** daily reference rates only; no intraday data; no forecasting.
- **Zotero collection:** `research/example_study`.

## Map

| Path | What |
| --- | --- |
| `research/brief.md` | question, deliverables, constraints (G1) |
| `research/landscape.md`, `research/notes/` | what is known, with sources |
| `hypotheses.yaml` | pre-registered hypotheses (G2, `sb freeze`) |
| `evidence/claims.yaml`, `evidence/sources.yaml`, `evidence/inbox.bib` | ledger |
| `pipelines/`, `contracts/` | project-only data (shared data lives in the hub) |
| `analysis/` | one script + report per hypothesis |
| `results/` | `results.json` + `results.tex` (generated) |
| `figures/`, `tables/` | generated outputs; `figures/tikz/` hand-made diagrams |
| `deliverables/` | LaTeX sources and PDFs |
| `reviews/` | verifier and referee reports |
| `public/` | README, LICENSE, CITATION.cff for the public repository |
| `log.md` | research log (decisions, gates) |

Build: `sb run` (analysis, figures, bib, lineage, paper, check; single steps: `sb run analysis figures`). Publish: `sb publish`.
The `make` targets are shortcuts for the same commands.
