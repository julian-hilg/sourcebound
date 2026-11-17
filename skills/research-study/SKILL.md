---
name: research-study
description: Run a research study in a Sourcebound research hub end to end as the lead agent, orchestrating subagents (scout, librarian, data-scout, pipeline-engineer, analyst, verifier, referee, writer). Research and hypotheses first, data and analysis next, deliverables (LaTeX house style) and publishing last, with every claim traceable. Use for "research topic X", "set up a study on …", "continue the study", market-inefficiency or data-driven research projects in <hub>.
---

# research-study: lead playbook

You are the **lead**. You plan, delegate, integrate, keep the ledger, and talk to the user.
Subagents do the legwork in parallel and hand back files. The rules every agent follows
are in the Sourcebound `AGENTS.md` (`$(sb which home)/AGENTS.md`); read it, and the
project's `AGENTS.md`, at the start of every session. The tooling is the `sb` CLI and the
`sourcebound` Python package (use `sb run ...` in the project, or `$(sb which python)`).
A project may live inside the hub or anywhere else; `sb doctor` shows which configuration,
data root and registry apply. If it reports errors, fix them (or ask the user) first.

## 0. Orient (every session)

1. `cd <project>`; `sb status`; read `log.md` (last entries) and
   `project.yaml` (`phase:`).
2. No project yet: `sb new <slug> --title "..." --lang de|en [--empty]`, then fill
   `research/brief.md` with the user (question, why, deliverables, constraints, budget).
   **Gate G1: the user approves the brief.**
3. Append a dated line to `log.md` for every phase change, gate and decision (who, what, why).

## 1. Landscape (parallel scouts)

- Split the question into 3 to 7 non-overlapping sub-questions (market structure, mechanism,
  prior literature, regulation, data availability, comparable markets, ...).
- Launch one `scout` per sub-question **in one message** (parallel). Use the brief template in
  `references/delegation.md`. Scale effort: simple fact = 1 scout, 5 to 10 calls; comparison =
  2 to 4 scouts, 10 to 15 calls each; open research = 5 to 7 scouts, then a second wave only
  for the gaps.
- Read the notes, then synthesise `research/landscape.md` yourself (the lead owns synthesis).
  Move accepted claims into `evidence/claims.yaml`, each with evidence and stance.
- Send the DOI list to the `librarian` (inbox, `sb bib import` with the user's Zotero open).
- `sb bib link` at the start: if the project's Zotero collection is missing, ask the user to
  create it (one click in Zotero). After the user has added papers and PDFs there, run
  `sb papers sync`; it copies the PDFs to the paper store and converts them in the background
  when a converter is configured. Scouts and the verifier read papers with `sb source <citekey>`.
- `verifier` on `landscape.md` before you build hypotheses on it.

## 2. Hypotheses (the core of the study)

- Draft `hypotheses.yaml` from the landscape: each with statement, `motivated_by` claims,
  prediction, test, data, metric, decision rule, kill criterion, priority.
  Good hypotheses are falsifiable, have a decision rule fixed in advance, and name the money
  or the effect size that would matter.
- `referee` in **design** mode on `hypotheses.yaml`; revise.
- **Gate G2**: show the user the hypotheses (table: id, statement, test, data, decision rule);
  after approval run `sb freeze` (date, hashes, tagged commit). From now on `sb check` reports
  any change to a frozen hypothesis. A justified change: add an entry under `amendments:`
  (`date`, `hypothesis: H2`, `reason`), tell the user, then `sb freeze --amend`. A hypothesis
  added later is either such an amendment or carries `exploratory: true`.

## 3. Data

- `data-scout` for the data needs of the frozen hypotheses (one per data domain, parallel).
  Present the ranked sources; **the user approves paid or legally sensitive sources**.
- `pipeline-engineer` per approved source (parallel when the sources are independent; they
  write different folders). Shared domains: contract in the registry, pipeline in the hub (`pipelines/`);
  project-only tables to `proj_<slug>` in the project.
- Check: the hub tests (`uv run pytest -q` in `$(sb which home)`), `sb lake tables`, row counts, a quick plausibility query.
- Scraping that runs for weeks: document the schedule in the pipeline README (cron/launchd
  line); do not install schedulers without the user.

## 4. Analysis (one analyst per hypothesis, parallel)

- Launch `analyst` agents for independent hypotheses in one message. Each reads data via
  `lake.read`, records numbers via `results.record`, writes `analysis/<hid>_report.md`, and
  runs only its own script (`sb run analysis/<script>.py`).
- When the analysts are done: commit the analysis code (`git add analysis pipelines contracts
  figures && git commit`), then `sb run analysis`. It rebuilds every result from the committed
  scripts; `sb check` warns about results that are stale, from uncommitted code, or from
  different snapshots of one table. Repeat this after every later change to an analysis.
- You record the decision in `hypotheses.yaml` (status + `results:` keys) and update the
  claims the result supports or refutes (`ref: R:<key>`).
- `referee` in **results** mode. Fix or run the requested robustness checks.

## 5. Deliverables

- Figures: `figures/make_figures.py` (sourcebound.plot; reads `results/*.parquet`), diagrams in
  `figures/tikz/` (sbtikz). Tables: written by the analysis scripts (`sourcebound.tables`).
- The deliverable folder is self-contained: `main.tex`, `sections/NN_*.tex` (people and
  agents), `generated/` (`sb sync`: results, tables, figures, diagrams, style files),
  `references.bib` (`sb bib sync`). It can be its own git repository linked to Overleaf.
- `writer` drafts sections (several writers only for separate section files; in a Markdown
  deliverable the notation is `{{result:key}}` and `[@key]`). Then
  `sb bib sync`, `sb lineage`, `sb build` (runs `sb sync`), `sb check`; all in order: `sb run`.
  `sb check` lists lines with a number typed by hand: replace each by a recorded result, or
  note in `log.md` why it is not a result (a threshold, a year, a quoted figure with its source).
- **After the user edited the text** (locally or on Overleaf): pull, run `sb review-edits`,
  then `sb check`, then a `verifier` on the listed files for the changed statements only.
  Agents change sections by targeted edits and commit after each task with a
  `Co-Authored-By:` trailer; a section a person touched is never regenerated.
- Single-file submission: `sb flatten`.
- LaTeX is optional: without it `sb build` skips the PDF, and a deliverable can be written
  in Markdown (`sb new --deliverable markdown`). Other formats (Word, HTML, posts) are not
  rendered here: run `sb handover` and pass `dist/handover/` to the tool that renders them.
- `verifier` on the deliverable, then `referee` in **draft** mode. Iterate until the
  verification report has no unsupported statement.

## 6. Publish (Gate G3)

- `sb publish` builds `dist/public` (allowlist from `project.yaml`, PDF only, no TeX, no raw
  data) and `dist/data` (Parquet + datapackage.json); fix every gate error.
- Show the user the bundle file list and the data plan (Zenodo for a DOI, R2 for a mirror).
  **Only after an explicit go**: upload data, set `publish.data_url`; the user then runs
  `sb publish --push` in a terminal (it asks for a typed confirmation and refuses to run
  for an agent). The same holds for `sb unblock`.

## Orchestration rules

- **Delegate by brief, not by chat.** Every subagent prompt follows `references/delegation.md`:
  objective, context files, boundaries, output path and format, effort budget, return format.
- **Files are the hand-off.** Subagents write to the paths you give and return the path plus a
  short summary; you read the file instead of relaying content through prompts.
- **Parallel when independent**, sequential when one output feeds the next. Never let two
  agents write the same file.
- **The lead owns** `hypotheses.yaml`, `project.yaml`, `log.md`, `research/landscape.md` and
  every gate. Subagents propose; you decide.
- **Checkpoints.** Long phases: write the plan to `log.md` first, so a new session (or a
  compacted context) can resume from files.
- **Ask the user** at G1, G2, G3, for money, legal grey zones, contacting third parties, and
  when a source blocks us. Do not ask about things the files already answer.
- **Agent teams** (experimental, enabled on this machine) only for long parallel engineering
  with separate folders; subagents are the default.

## References

- `references/delegation.md`: brief template and examples for each agent.
- `references/structure.md`: folder layout of hub and project, data flow, file formats.
