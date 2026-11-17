# Delegation briefs

Every subagent starts with no memory of this conversation. Its prompt must stand alone.

## Template

```
Objective: <one sentence; one question or one deliverable>
Project:   <path>  (read AGENTS.md there and the Sourcebound AGENTS.md)
Context:   <files to read first, e.g. research/brief.md, hypotheses.yaml#H3>
Scope:     <what is in>
Not yours: <what other agents cover; "do not research X, scout-2 does">
Output:    <exact path> in the format of your agent definition
Budget:    <e.g. 15 searches/fetches; or: stop after the fixture tests pass>
Return:    path + <=5 lines: answer, confidence, open points
```

## Examples

**scout**
```
Objective: How fast and how symmetrically do fuel retailers pass wholesale price moves
           through to retail prices? What does the literature find?
Project:   <hub>/fuel_passthrough
Context:   research/brief.md
Scope:     rockets-and-feathers literature, evidence by country, methods used
Not yours: data sources (data-scout), regulation and legal (scout-4)
Output:    research/notes/passthrough_literature.md
Budget:    15 searches/fetches
Return:    path + 3-sentence answer + number of strong/medium/weak findings
```

**data-scout**
```
Objective: Data for H1-H3: retail price quotes per region and product, daily.
Context:   hypotheses.yaml (H1-H3), <registry>/datasources/ (existing entries)
Output:    <registry>/datasources/<id>.yaml per candidate + ranked table in your reply
Budget:    at most 5 page loads per site; stop at any block
```

**pipeline-engineer**
```
Objective: Pipeline for datasource ecb_data_portal -> market.ecb_fx_daily (approved by user 2026-11-09)
Context:   <registry>/datasources/ecb_data_portal.yaml, pipelines/ecb_fx (reference)
Output:    <registry>/contracts/market/<table>.yaml, pipelines/<source>/ (pipeline.py, fixtures/, test_pipeline.py)
Done when: pytest passes offline, one small run loaded, snapshot id reported
```

**analyst**
```
Objective: Test H3 exactly as registered (hypotheses.yaml#H3, frozen 2026-11-20).
Output:    analysis/h3_passthrough.py, analysis/h3_report.md, results keys h3.*
Run:       only your script: sb run analysis/h3_passthrough.py
Not yours: other hypotheses; figures (lead draws them in figures/make_figures.py)
```

**verifier**
```
Objective: Verify every checkable statement in deliverables/paper/sections/01_*.tex to 04_*.tex.
Output:    reviews/verification_<date>.md
```

**referee**
```
Mode:      design | results | draft
Objective: Review hypotheses.yaml before freeze (design mode).
Output:    reviews/referee_design_<date>.md
```

**writer**
```
Objective: Draft the section "Results" from analysis/h*_report.md.
Not yours: introduction and literature (other writer); no new numbers, ask the lead.
Output:    deliverables/paper/sections/04_results.tex (or .md in a Markdown deliverable); `sb build` and `sb check` clean
```
