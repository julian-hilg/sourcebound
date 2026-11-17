# Structure, formats and data flow

## Hub (`<hub>` = `sb which home`) and data root

| Path | Content | Who writes |
| --- | --- | --- |
| `AGENTS.md` | rules for every agent | user / template |
| `.claude/agents/*.md` | subagents (shipped with the hub) | template |
| `hub.toml`, `~/.config/sourcebound/config.toml` | data root, catalog, fetch etiquette, Zotero, GitHub (hub.toml applies inside the hub, the user configuration elsewhere; `sb doctor`) | user |
| `src/sourcebound/` | lake, contracts, fetch, ledger, results, tables, zotero, publish, cli | template |
| `<data root>/registry/contracts/<domain>/<table>.yaml` | shared data contracts (the hub's `contracts/` holds examples) | pipeline-engineer |
| `pipelines/<source>/` | shared ingestion + fixtures + tests | pipeline-engineer |
| `<data root>/registry/datasources/<id>.yaml` | source register (status candidate -> approved -> active) | data-scout, user approves |

## Project (`<hub>/<slug>` or any folder)

Deliverable folder `deliverables/paper/`: `main.tex` + `sections/NN_*.tex` (written by the
writer and the user), `generated/` (`sb sync`, never edited), `references.bib` (`sb bib sync`),
style files. No path leaves the folder, so it compiles alone and on Overleaf.

| Path | Content | Who writes |
| --- | --- | --- |
| `project.yaml` | slug, title, lang, phase, reads/owns, deliverables, publish allowlist | lead |
| `AGENTS.md` | project brief for agents | lead |
| `log.md` | dated decisions and gates | lead |
| `research/brief.md` | question, deliverables, constraints (G1) | lead + user |
| `research/notes/*.md` | scout findings with evidence | scout |
| `research/landscape.md` | synthesis | lead |
| `hypotheses.yaml` | pre-registration (G2, `sb freeze`; changes only by amendment and `sb freeze --amend`) | lead |
| `evidence/claims.yaml` | claim ledger | lead (from scout proposals) |
| `evidence/sources.yaml` | web sources W-xxxx with archived snapshot | `sb snap` |
| `evidence/inbox.bib` | references not yet in Zotero | librarian |
| `pipelines/`, `contracts/` | project-only data (`proj_<slug>`) | pipeline-engineer |
| `analysis/hN_*.py`, `analysis/hN_report.md` | one test per hypothesis | analyst |
| `results/results.json`, `results.tex` | recorded numbers (generated) | analysis scripts |
| `results/*.parquet` | data for figures (generated) | analysis scripts |
| `figures/make_figures.py`, `figures/*.pdf` | sourcebound.plot figures | lead / writer |
| `figures/tikz/*.tex` | diagrams (pipeline, DAG, timeline templates) | writer |
| `tables/*.tex` + `*.csv` | generated table bodies | analysis scripts, `sb lineage` |
| `deliverables/paper/` | `main.tex` + `sections/` (or `sections/*.md` in a Markdown deliverable); the PDF goes to `deliverables/<slug>.pdf` | writer, user |
| `dist/handover/` | format-neutral export for other renderers (`sb handover`) | generated |
| `reviews/verification_*.md`, `reviews/referee_*.md` | quality gates | verifier, referee |
| `public/` | README, LICENSE, CITATION.cff of the public repository | lead |
| `dist/` | publish bundle (generated, ignored by git) | `sb publish` |

## Data flow and identifiers

```
source --Fetcher--> raw (sha256) --parse--> lake table (raw_ref, snapshot N)
      --lake.read--> analysis --results.record--> results.json (script, git, {table: N})
      --results.tex--> \result{key} in the deliverable --sb lineage--> data appendix
```

| Identifier | Meaning | Resolves via |
| --- | --- | --- |
| `Cont2001EmpiricalProperties` | Better BibTeX citekey | Zotero / `inbox.bib` |
| `W-0001` | archived web source | `evidence/sources.yaml` -> raw archive |
| `R:h1.kurtosis` | recorded result | `results/results.json` |
| `data:market.ecb_fx_daily@12` | table at snapshot | lake catalog |
| `C001`, `H1` | claim, hypothesis | ledger files |
