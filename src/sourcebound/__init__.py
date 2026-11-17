"""sourcebound -- shared research infrastructure for <hub>.

    from sourcebound import lake, results
    fx = lake.read("market.ecb_fx_daily")          # polars DataFrame, lineage recorded
    results.record("h1.kurtosis", 4.2, fmt="{:.1f}", hypothesis="H1")

Modules
    config     hub.toml / project.yaml discovery
    lake       data client: DuckLake catalog over Parquet (read / write / export)
    contracts  YAML data contracts: validation, Frictionless datapackage export
    fetch      polite HTTP fetcher with immutable raw archive and block detection
    sources    custom and private sources: register entry, archived documentation, files, databases
    ledger     hypotheses, claims, web sources: validation and freeze
    results    numbers for the deliverable, with provenance -> results.tex macros
    tables     booktabs table bodies in the house style
    zotero     Better BibTeX: export exactly the cited keys, DOI inbox
    deliverable  LaTeX deliverable folders: sync, build (LaTeX optional), review of manual edits
    handover   format-neutral export (Markdown, results, tables, figures) for other renderers
    publish    production bundle for GitHub (no TeX sources, no raw data)
"""
__version__ = "0.1.0"
