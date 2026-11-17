# Research hub: rules for every agent and every project

**Scope.** These rules apply to every project (a folder with a `project.yaml`, inside this
folder or anywhere else; projects elsewhere import this file through their `CLAUDE.md`) and
to the hub itself. Other folders without `project.yaml`
keep their own rules; where their `AGENTS.md`/`CLAUDE.md` conflicts with this file, theirs wins.

This folder is a research hub. Each folder with a `project.yaml` is one project: a **study**
(one question, hypotheses, a paper) or a **desk** (`kind: desk`: ongoing research on a topic,
whose outputs are pieces such as posts, notes and briefings). Shared
code (`src/sourcebound`), shared pipelines (`pipelines/`) and the subagents
(`.claude/agents/`) live here. Data lives outside, in one data root per machine (the lake,
default `~/research-lake`): tables, raw responses and the **registry** of shared data
contracts (`registry/contracts/`) and data sources (`registry/datasources/`). The copies in
this folder's `contracts/` and `datasources/` are examples and a fallback. `sb doctor`
prints the resolved configuration; `sb which registry` prints the registry path.
Documentation: `README.md` and `docs/`.

## 1. Paradigm: research first, deliverables last

| Phase | Output (files) | Gate |
| --- | --- | --- |
| 0 Brief | `research/brief.md`: question, why it matters, deliverables, constraints | **G1** user approves the brief |
| 1 Landscape | `research/landscape.md`, `research/notes/*.md`, claims in `evidence/claims.yaml`, sources in Zotero / `evidence/sources.yaml` | every claim has evidence |
| 2 Hypotheses | `hypotheses.yaml`: prediction, test, data, decision rule, kill criterion | **G2** user approves, then `sb freeze` |
| 3 Data | data sources in the registry (`datasources/`), contracts, pipelines with fixture tests, tables in the lake | `pytest`, contracts valid |
| 4 Analysis | `analysis/hN_*.py`, `results/results.json` (via `sourcebound.results`) | each hypothesis decided by its rule |
| 5 Review | `reviews/verification_*.md` (claims vs evidence), `reviews/referee_*.md` | no unsupported claim left |
| 6 Deliverables | `deliverables/` (LaTeX, house style), figures, tables | `sb check` clean |
| 7 Publish | `dist/public` (GitHub, no TeX sources), `dist/data` (Zenodo / R2) | **G3** user says publish |

No deliverable prose before phase 4 results exist. Hypotheses are written *before* the
data is analysed. `sb freeze` stores a hash of every hypothesis; `sb check` then reports any
change. A change needs an entry under `amendments:` (`hypothesis:`, `reason:`) and
`sb freeze --amend`; a hypothesis added later is tested only with `exploratory: true` or
after such an amendment. Anything not pre-registered is labelled exploratory.

### Desks: ongoing research without a final deliverable

A desk (`sb new SLUG --kind desk`) follows a topic and produces **pieces** (`pieces/<id>/`: a
post, a note, a trade idea, a briefing). The table above does not apply: there are no
hypotheses to freeze, no gates G1 and G2 and no paper. What stays:

| Step | Output | Rule |
| --- | --- | --- |
| Collect | `research/notes/*.md`; sources by `sb snap URL` (web page) or `sb doc FILE` (report, any local file) | every finding names its source |
| Count | `analysis/*.py` recording with `sourcebound.results` | a number from data is a recorded result |
| Write | `sb piece add`; text in `pieces/<id>/text.md`, structured content (e.g. `slides.yaml`) beside it | section 2 applies in full |
| Check | `sb piece check <id>` | no error left |
| Render | `sb render <id> --template ID` | registered template and design only |
| Decide | status `approved`, `scheduled`, `published` | **the user's decision** (G3 for pieces) |

- A piece may be written from existing reports in a local folder: register each with `sb doc`
  first, read it with `sb source W-xxxx`, cite it. Never quote a file that is not registered.
- A number quoted from a source (not computed) is written out with its citation in the same
  sentence; `sb piece check` lists such lines so they can be confirmed.
- An agent sets a piece to `draft` or `review`, never further, and never posts or sends anything.
- If a desk question becomes a claim about cause or effect that needs testing, it is a study:
  say so and propose one.

## 2. Traceability: no source, no claim

- Every substantive statement in notes and deliverables rests on evidence of one of four kinds:
  Zotero citekey (`\cite{key}`, with page or quote in the ledger), web source `W-0001`
  (archived with `sb snap`), result `R:<key>`, or data `data:<schema>.<table>@<snapshot>`.
- Numbers in deliverables come only from `\result{key}` (recorded by an analysis script).
  Never type a computed number by hand; `sb check` lists lines that look like it.
- Results count only when a committed script of the project recorded them: commit the analysis
  code, then `sb run analysis` (it rebuilds all results from scratch). `sb check` warns about
  results from uncommitted code or mixed data snapshots; `sb publish` refuses them.
- Own estimates are labelled as such (claim kind `estimate`), assumptions as `assumption`.
- Conflicting evidence is recorded (`stance: contradicts`), not dropped. Status `contested` is fine.
- Never invent a citation, a page number, a quote, a URL or a data value. If unsure: claim
  status `open` and say so.

## 3. Data

- **Raw is immutable.** Every response is archived unchanged (`sourcebound.fetch`); staged
  tables carry `raw_ref` (sha256). Tables must be rebuildable from raw (`--reparse`).
- **Contracts first.** A shared table (schema `market`, `retail`, `geo`, `macro`, ...) has a
  YAML contract in the registry (`<registry>/contracts/<schema>/`) before the first write. Project tables use
  `proj_<slug>` and live in the project's `contracts/`.
- **Shared vs project.** Data useful beyond one study (benchmarks, prices, geography) is a
  shared table with a hub pipeline. Project-specific derivations stay in `proj_<slug>`.
  Promote a project table by moving its contract and pipeline to the hub.
- Read and write only through `sourcebound.lake` (lineage is recorded automatically).
  Apps read the same catalog (`docs/data-access.md`).
- No personal data unless the brief explicitly allows it; pseudonymise individuals.

## 4. Scraping and data access

Ask for an API or data cooperation first. Otherwise, only via `sourcebound.fetch.Fetcher`,
which enforces these rules (do not work around them):

- One request per host every 6+ seconds, honest User-Agent (the tool's own name, no browser string), robots.txt respected,
  conditional requests, no duplicate fetches. Design for few requests (one page = many rows).
- No logins, no proxies or IP rotation, no CAPTCHA solving, no fingerprint spoofing.
- 401/403/429/451/503 or a challenge page **stops that host** (`BLOCKED.<host>` marker). Report it to
  the user; never retry automatically. Only the user runs `sb unblock` (in a terminal; it asks
  for a typed confirmation). The request interval holds across all processes on the machine.
- Prefer the JSON endpoint the page loads itself; Playwright (`Fetcher.render`) only if needed.
- Continuous collection is a **job** (`sb job`): a pipeline with fixture tests, run on a schedule
  the user sets. A job changes nothing above: same fetcher, same limits, and a stopped host
  fails the job until the user has looked. Never add a job or shorten its interval yourself.
- Note terms of use and legal points (database rights, competition law, GDPR) in the source's
  `<registry>/datasources/<id>.yaml`. Publish aggregates, not other people's databases.

Custom and private sources (a provider's API, an internal database, files sent by a provider):

- Register the source first: `sb datasource add <id> --name "..."`. Onboard it from what the
  provider offers: its MCP server where one exists (save its tool list to a JSON file),
  otherwise its API documentation. Archive that documentation for good with
  `sb datasource docs <id> FILE|URL ...`; it is kept unchanged in
  `<registry>/datasources/<id>/docs/` and shared by all projects. Read it there before writing
  a pipeline; archive the new version when the provider changes it.
- Credentials are only those the provider issued for this access. The register entry names an
  environment variable (`auth: {env: ...}` for a token, `database: {password_env: ...}` or `connection_env:` for a database
  URI); the secret itself never enters a file, a manifest or a log. No website logins, no
  shared or borrowed accounts.
- Manual files go into the raw archive with `sb ingest FILE --source <id>`; database extracts
  with `sourcebound.sources.query(source, sql)` (the extract and the query text are archived).
  Tables built from either carry `raw_ref` and are rebuildable like any other.
- A licence that starts with `restricted` or `proprietary` in the table's contract keeps the
  table out of `sb publish`. Proprietary data never goes into a project repository.

## 5. Agents

The main session is the **lead**: it plans, delegates, integrates and talks to the user. It
follows the `research-study` skill. Subagents (in `.claude/agents/`):

| Agent | Job | Writes |
| --- | --- | --- |
| `scout` | evidence on ONE sub-question (literature, web, official statistics) | `research/notes/<topic>.md` |
| `librarian` | citekeys, DOIs, Zotero inbox, bibliography checks | `evidence/inbox.bib`, reports |
| `data-scout` | find and assess data sources (access, licence, legal, cost) | `<registry>/datasources/<id>.yaml` (status candidate) |
| `pipeline-engineer` | contract + fetch/parse/validate pipeline with fixture tests | `<registry>/contracts/` or project `contracts/`, `pipelines/` |
| `analyst` | test ONE frozen hypothesis exactly as registered | `analysis/`, results |
| `verifier` | check every claim in a draft against its evidence | `reviews/verification_*.md` |
| `referee` | adversarial review: identification, robustness, alternatives | `reviews/referee_*.md` |
| `writer` | deliverable sections in LaTeX house style from frozen results | `deliverables/` |

Delegation rules: one objective per subagent, explicit boundaries ("not X, that is another
agent's job"), output format and file path given, effort budget given. Subagents write
results to files and return the path plus a five-line summary. Run independent subagents in
parallel. Only the lead edits `hypotheses.yaml`, `project.yaml` and `log.md`.

## 6. Deliverables and style

- LaTeX is optional. Without a TeX installation everything works except compiling the PDF
  (`sb build` says so and carries on). A deliverable may also be written in Markdown
  (`deliverables/<name>/sections/*.md`, created by `sb new --deliverable markdown`) with
  `{{result:key}}` for numbers and `[@key]` for citations; the same rules apply.
- `sb handover` writes `dist/handover/`, the format-neutral copy of the deliverables (Markdown
  sections, results, tables as CSV, figures, bibliography, ledger). The web view and the format
  plugins render from it. A handover is not a publication bundle.
- LaTeX: each deliverable is a self-contained folder: `main.tex` (preamble and
  `\input{sections/NN_*}`), `sections/` (prose, edited by people and agents), `generated/`
  (results, tables, figures, diagrams; written only by `sb sync`), `references.bib`
  (`sb bib sync`) and the style files (built-in `sbpaper`, or the user's own template via
  `sb new --deliverable`). No path leaves the folder.
- Edits by a person are kept: run `sb review-edits` before changing a deliverable, change
  sections by targeted edits, never regenerate a section a person touched, and commit agent
  edits with a `Co-Authored-By:` trailer. Black type only, blue citations, square corners, no paragraph indent.
- Other formats (Word, slides and posts) are rendered by plugins from registered templates in a
  registered design: `sb render TARGET --template ID`. Never restyle output by hand, never put
  an organisation's design or logo into the checkout (it lives in a pack, `sb pack install`),
  and do not create or change templates unless the user asks for exactly that.
- A Word file a person edited is theirs: `sb word status|refresh|pull` (Word plugin) read it and
  update recorded numbers in place; never re-render over it.
- The web view (`sb ui`, optional) shows the same files; it is not a place to pass a gate. Plans for
  further deliverables are notes in `deliverables/notes.yaml` (`sb note`), not deliverables.
- Data figures: `sourcebound.plot` (matplotlib, sizes and fonts from the document). Diagrams: TikZ with
  `sbtikz` (`figures/tikz/`). Tables: `sourcebound.tables` (booktabs bodies + CSV twin).
- Results: `\usepackage{sbresults}` and `\result{key}`; data appendix via `sb lineage`.
- Bibliography: `sb bib sync` (exactly the cited keys, from Zotero). Never edit `references.bib`.
- Literature: a project's reading list is its Zotero collection (`zotero_collection:` in
  `project.yaml`, more under `zotero_collections:`). Collections are created in Zotero by the
  user; `sb bib link` shows whether they exist. `sb papers sync` copies the PDFs of these
  collections and of cited items into the paper store in the data root (`library/`, keyed by
  sha256) and starts the optional conversion to Markdown in the background.
  `sb source <citekey> [--grep WORD] [--page N]` prints a paper's text for checking a quote or
  a page; the PDF page is the authority where converted text looks wrong. PDFs and their text
  are copyrighted: never copy them into a project, a bundle or a handover.

## 7. Publishing

Only `sb publish` builds what leaves the machine: an allowlist from `project.yaml`, no
`.tex`/`.bib`, no raw data, no secrets, files under 20 MB, data as Parquet with
`datapackage.json` for Zenodo / R2. **Pushing (`--push`) and uploading need the user's
explicit go (G3)**: the user runs `sb publish --push` in a terminal and confirms it there. The
working repository of a project stays private; the public one is private too unless
`publish.visibility: public` is set.

- A piece leaves the machine only by the user's hand. Nothing in Sourcebound posts to a network;
  `scheduled` means "the user intends to post it then".

## 8. Language and tone

Project language is set in `project.yaml` (`de` or `en`). Write plainly: short sentences,
units with every number, dates as YYYY-MM-DD. No marketing language.
