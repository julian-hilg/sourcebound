"""Core behaviour of sourcebound, offline, against a temporary hub and lake."""
from __future__ import annotations

import http.server
import json
import os
import threading
from pathlib import Path

import polars as pl
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Never read the developer's own configuration or lake."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for k in ("SB_CONFIG", "SB_LAKE_ROOT", "SB_CATALOG", "SB_DATA_PATH"):
        monkeypatch.delenv(k, raising=False)
    from sourcebound import lake
    lake._CON = None
    lake.READS.clear()
    yield
    lake._CON = None


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    """A fresh hub (hub.toml + contracts) with its own lake, as the working directory."""
    h = tmp_path / "hub"
    (h / "contracts" / "market").mkdir(parents=True)
    (h / "hub.toml").write_text(
        "[lake]\nroot = '%s'\n[fetch]\nuser_agent = 'sourcebound-tests'\nmin_interval = 0.0\njitter = 0.0\n"
        "[templates]\nproject = '%s'\n" % (tmp_path / "lake", ROOT / "templates" / "project"))
    (h / "contracts" / "market" / "prices.yaml").write_text(yaml.safe_dump({
        "name": "market.prices", "title": "Test prices", "primary_key": ["date", "id"],
        "columns": {"date": {"type": "date"}, "id": {"type": "string"},
                    "price": {"type": "double", "min": 0}}}))
    monkeypatch.chdir(h)
    from sourcebound import lake
    lake._CON = None
    lake.READS.clear()
    yield h
    lake._CON = None


def _prices(n=3, price=1.0):
    return pl.DataFrame({"date": pl.date_range(pl.date(2026, 1, 1), pl.date(2026, 1, n), eager=True),
                         "id": ["a"] * n, "price": [price + i for i in range(n)]})


# ----------------------------------------------------------------------------- results
def test_number_formats():
    from sourcebound.results import format_value, to_tex
    assert format_value(1234.5, "{:,.1f}", False) == "1,234.5"
    assert format_value(1234.5, "{:,.1f}", True) == "1.234,5"
    assert format_value(0.0312, "pct1", True) == "3,1 %"
    assert to_tex(0.0312, "3,1 %") == "3{,}1\\,\\%"
    assert to_tex(1.9e-26, "1.9e-26") == "\\ensuremath{1.9\\times 10^{-26}}"
    assert to_tex(-0.5, "-0.50") == "\\ensuremath{-}0.50"
    assert to_tex("2026-01-05", "2026-01-05") == "2026-01-05"


# ----------------------------------------------------------------------------- contracts + lake
def test_contract_violations(hub):
    from sourcebound import contracts
    c = contracts.find("market.prices", hub_root=hub)
    bad = pl.concat([_prices(), _prices(1, price=-5.0)])
    errs = c.validate(bad)
    assert any("primary key" in e for e in errs)
    assert any("below min" in e for e in errs)
    assert c.validate(_prices()) == []


def test_lake_roundtrip_time_travel_and_contract_gate(hub):
    from sourcebound import lake
    s1 = lake.write(_prices(3), "market.prices", note="first")
    s2 = lake.write(_prices(2, price=10.0), "market.prices", mode="upsert", note="update")
    assert s2 > s1
    now = lake.read("market.prices").sort("date")
    assert now["price"].to_list() == [10.0, 11.0, 3.0]
    assert lake.read("market.prices", as_of=s1)["price"].sort().to_list() == [1.0, 2.0, 3.0]
    assert lake.READS["market.prices"] == s1
    with pytest.raises(ValueError, match="contract"):
        lake.write(_prices(), "market.undocumented")
    with pytest.raises(ValueError, match="violates"):
        lake.write(_prices(1, price=-1.0), "market.prices")


# ----------------------------------------------------------------------------- ledger
def test_ledger_detects_broken_references(hub):
    from sourcebound import config, ledger
    p = hub / "demo"
    (p / "evidence").mkdir(parents=True)
    (p / "project.yaml").write_text("slug: demo\ntitle: Demo\nlang: en\n", encoding="utf-8")
    (p / "hypotheses.yaml").write_text(yaml.safe_dump({"frozen": None, "hypotheses": [
        {"id": "H1", "statement": "s", "prediction": "p", "test": "t", "data": ["market.prices"],
         "decision_rule": "r", "kill": "none", "status": "supported", "motivated_by": ["C404"]}]}))
    (p / "evidence" / "claims.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C001", "text": "x", "status": "supported",
         "evidence": [{"ref": "W-0404", "stance": "supports"}]},
        {"id": "C002", "text": "y", "status": "supported",
         "evidence": [{"ref": "R:none", "stance": "context"}]}]}))
    errs, _ = ledger.check(config.project(p), resolve_citekeys=False)
    text = "\n".join(errs)
    for needle in ("C404", "W-0404", "R:none", "never frozen", "without linked results",
                   "no supporting evidence"):
        assert needle in text, needle


# ----------------------------------------------------------------------------- fetcher
class _Handler(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []
    robots_status = 200

    def do_GET(self):  # noqa: N802
        _Handler.hits.append(self.path)
        if self.path == "/robots.txt":
            body, code = b"User-agent: *\nDisallow: /private\n", _Handler.robots_status
        elif self.path.startswith("/block"):
            body, code = b"slow down", 429
        elif self.path.startswith("/auth"):
            body, code = json.dumps({"got": self.headers.get("Authorization") or self.headers.get("X-Api-Key")}).encode(), 200
        elif self.path.startswith("/to/"):                          # redirect to another local server
            self.send_response(302)
            port, _, target = self.path[4:].partition("/")
            self.send_header("Location", f"http://127.0.0.1:{port}/{target or 'auth'}")
            self.end_headers()
            return
        else:
            body, code = json.dumps({"path": "same"}).encode(), 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    _Handler.hits, _Handler.robots_status = [], 200
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.mark.parametrize("status, allowed", [(404, True), (403, False), (401, False), (503, False)])
def test_a_refused_robots_file_allows_nothing(hub, server, status, allowed):
    from sourcebound import fetch
    from sourcebound.fetch import Blocked, Fetcher
    fetch._robots.clear()
    _Handler.robots_status = status
    f = Fetcher("testsrc", min_interval=0, jitter=0)
    if allowed:                                                    # no robots.txt: nothing is disallowed
        assert f.get(server + "/private/x")[1].status == 200
    else:                                                          # refused or failing: the site has not shown its rules
        with pytest.raises(Blocked, match="robots.txt disallows"):
            f.get(server + "/a")
        assert _Handler.hits == ["/robots.txt"]                    # the page itself was never requested
    fetch._robots.clear()


def test_fetcher_archives_dedups_and_stops(hub, server):
    from sourcebound.fetch import Blocked, Fetcher
    f = Fetcher("testsrc", min_interval=0, jitter=0)
    _, r1 = f.get(server + "/a")
    _, r2 = f.get(server + "/b")
    assert r1.sha256 == r2.sha256                                  # identical bytes stored once
    assert len(list((f.dir).glob("*/*/*/*.zst"))) == 1
    with pytest.raises(Blocked):
        f.get(server + "/private/x")                               # robots.txt
    with pytest.raises(Blocked):
        f.get(server + "/block")                                   # 429 stops the source
    n = len(_Handler.hits)
    with pytest.raises(Blocked):
        f.get(server + "/c")                                       # ... and nothing reaches the server
    assert len(_Handler.hits) == n


# ----------------------------------------------------------------------------- cli
def test_new_project_copy_and_rename(hub):
    from sourcebound.cli import main
    main(["new", "my_study", "--title", "My Study", "--empty"])
    p = hub / "my_study"
    paper = p / "deliverables" / "paper"
    assert "\\input{sections/01_introduction}" in (paper / "main.tex").read_text(encoding="utf-8")
    assert sorted(x.name for x in (paper / "sections").iterdir()) == ["00_abstract.tex", "01_introduction.tex"]
    assert "slug: my_study" in (p / "project.yaml").read_text(encoding="utf-8")
    assert yaml.safe_load((p / "hypotheses.yaml").read_text(encoding="utf-8"))["hypotheses"] == []


# ----------------------------------------------------------------------------- configuration
def _init(tmp_path, *extra):
    from sourcebound.cli import main
    main(["init", "--data-root", str(tmp_path / "store"), *extra])


def test_user_config_serves_projects_anywhere(tmp_path, monkeypatch, capsys):
    from sourcebound import config, contracts, lake
    from sourcebound.cli import main
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    assert config.hub(required=False) is None
    _init(tmp_path)
    store = tmp_path / "store"
    for d in ("data", "raw", "registry/contracts/market", "registry/datasources"):
        assert (store / d).is_dir(), d
    assert (store / "registry" / "contracts" / "market" / "ecb_fx_daily.yaml").exists()   # seeded example
    h = config.hub()
    assert (h.source, h.lake_root, h.root) == ("user", store.resolve(), ROOT)
    assert h.contracts_dir == store.resolve() / "registry" / "contracts"
    assert h.datasource("ecb_data_portal").is_relative_to(store.resolve())

    main(["new", "far_away", "--title", "Far Away", "--empty"])
    p = work / "far_away"
    assert "AGENTS.md" in (p / "CLAUDE.md").read_text(encoding="utf-8")            # research rules imported
    monkeypatch.chdir(p)
    c = contracts.Contract.load(h.contracts_dir / "market" / "ecb_fx_daily.yaml")
    assert contracts.find("market.ecb_fx_daily", hub_root=h.root, registry=h.registry).path == c.path
    (h.contracts_dir / "market" / "prices.yaml").write_text(yaml.safe_dump({
        "name": "market.prices", "primary_key": ["date", "id"],
        "columns": {"date": {"type": "date"}, "id": {"type": "string"}, "price": {"type": "double"}}}))
    lake.write(_prices(), "market.prices")
    assert lake.read("market.prices").height == 3 and (store / "catalog.sqlite").exists()
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        main(["doctor"])
    out = capsys.readouterr().out
    assert e.value.code == 0 and "[user]" in out and "0 errors" in out, out


def test_resolution_order(hub, tmp_path, monkeypatch):
    from sourcebound import config
    _init(tmp_path)                                              # a user configuration exists ...
    assert config.hub().source == "hub"                          # ... but the nearest hub.toml wins
    assert config.hub().lake_root == tmp_path / "lake"
    p = hub / "pinned"
    p.mkdir()
    (p / "project.yaml").write_text("slug: pinned\ndata_root: ../../elsewhere\n", encoding="utf-8")
    h = config.hub(p)
    assert (h.lake_root, h.lake_root_from) == ((tmp_path / "elsewhere").resolve(), "project.yaml")
    assert h.registry == h.lake_root / "registry" and h.catalog.startswith(f"sqlite:{h.lake_root}")
    monkeypatch.setenv("SB_LAKE_ROOT", str(tmp_path / "env"))
    assert config.hub(p).lake_root == tmp_path / "env"
    monkeypatch.setenv("SB_CONFIG", str(config.user_config_path()))
    monkeypatch.delenv("SB_LAKE_ROOT")
    assert (config.hub().source, config.hub().lake_root) == ("env", (tmp_path / "store").resolve())


def test_registry_contract_beats_hub_copy(hub, tmp_path):
    from sourcebound import config, contracts
    h = config.hub()
    assert h.contracts_dir == hub / "contracts"                  # no registry yet: the hub's contracts
    reg = h.registry / "contracts" / "market"
    reg.mkdir(parents=True)
    spec = yaml.safe_load((hub / "contracts" / "market" / "prices.yaml").read_text(encoding="utf-8")) | {"title": "Registry"}
    (reg / "prices.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    assert contracts.find("market.prices", hub_root=h.root, registry=h.registry).title == "Registry"
    assert h.contracts_dir == h.registry / "contracts"


def test_public_bundle_data_beats_user_config(tmp_path, monkeypatch):
    from sourcebound import lake
    _init(tmp_path)
    clone = tmp_path / "clone"
    (clone / "data").mkdir(parents=True)
    _prices(2).write_parquet(clone / "data" / "market.prices.parquet")
    monkeypatch.chdir(clone)
    assert lake.read("market.prices").height == 2 and lake.READS["market.prices"] is None


# ----------------------------------------------------------------------------- deliverables
def test_deliverable_is_self_contained_after_sync(hub, monkeypatch):
    from sourcebound import config, deliverable
    from sourcebound.cli import main
    main(["new", "study", "--title", "Study"])
    p = hub / "study"
    monkeypatch.chdir(p)
    for rel, body in (("results/results.tex", "\\sbsetresult{a}{1}\n"), ("tables/t.tex", "x"), ("figures/f.pdf", "%PDF")):
        (p / rel).parent.mkdir(exist_ok=True)
        (p / rel).write_text(body, encoding="utf-8")
    d = p / "deliverables" / "paper"
    changed = deliverable.sync(config.project(p))["deliverables/paper"]
    for rel in ("generated/results.tex", "generated/tables/t.tex", "generated/figures/f.pdf",
                "generated/tikz/pipeline.tex", "sbpaper.cls", "sbresults.sty", "sbtikz.sty"):
        assert (d / rel).exists() and rel in changed, rel
    code = "\n".join(ln for x in d.rglob("*.tex") for ln in x.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("%"))
    assert "../" not in code                                     # nothing points outside the folder
    assert deliverable.sync(config.project(p))["deliverables/paper"] == []       # idempotent
    (p / "tables" / "t.tex").unlink()
    assert "-generated/tables/t.tex" in deliverable.sync(config.project(p))["deliverables/paper"]
    assert not (d / "generated" / "tables" / "t.tex").exists()


def test_own_latex_template(hub, tmp_path):
    from sourcebound import config
    from sourcebound.cli import main
    house = tmp_path / "house"
    house.mkdir()
    (house / "house.tex").write_text("% sample\n\\documentclass[a4paper]{article}\n\\usepackage{house}\n"
                                     "\\title{Sample Title}\n\\begin{document}\nSample text.\n\\end{document}\n")
    (house / "house.sty").write_text("\\ProvidesPackage{house}\n", encoding="utf-8")
    (house / "references.bib").write_text("@book{sample}\n", encoding="utf-8")
    with (hub / "hub.toml").open("a") as fh:
        fh.write("\n[templates.latex]\nhouse = '%s'\n" % house)
    config._load_hub.cache_clear()
    main(["new", "styled", "--title", "Styled", "--empty", "--deliverable", "house"])
    d = hub / "styled" / "deliverables" / "paper"
    tex = (d / "main.tex").read_text(encoding="utf-8")
    assert "\\documentclass[a4paper]{article}\n\\usepackage{sbresults}\n\\sbresults{generated/results.tex}" in tex
    assert "\\title{Styled}" in tex and "Sample" not in tex and "\\input{sections/01_introduction}" in tex
    assert (d / "house.sty").exists() and not (d / "references.bib").exists()
    with pytest.raises(SystemExit, match="LaTeX template"):
        main(["new", "other", "--title", "Other", "--deliverable", "missing"])


def test_review_edits_lists_what_a_person_changed(hub, monkeypatch):
    import subprocess

    from sourcebound import config, deliverable
    from sourcebound.cli import main
    main(["new", "study", "--title", "Study"])
    p = hub / "study"
    git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *a],
                                    cwd=p, check=True, capture_output=True)
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "--allow-empty", "-m", "Draft sections\n\nCo-Authored-By: An Agent <agent@example.org>")
    sec = p / "deliverables" / "paper" / "sections" / "05_conclusion.tex"
    sec.write_text(sec.read_text(encoding="utf-8") + "The effect is 3.7 percent \\parencite{New2020}, see \\result{h2.ratio}.\n")
    git("commit", "-q", "-am", "edit by hand")
    intro = p / "deliverables" / "paper" / "sections" / "01_introduction.tex"
    intro.write_text(intro.read_text(encoding="utf-8") + "One more sentence, not committed.\n")
    rep = deliverable.review(config.project(p))["files"]
    assert sorted(rep) == ["deliverables/paper/sections/01_introduction.tex", "deliverables/paper/sections/05_conclusion.tex"]
    c = rep["deliverables/paper/sections/05_conclusion.tex"]
    assert (c["added_lines"], c["cites"], c["results"]) == (1, ["New2020"], ["h2.ratio"])
    assert len(c["typed_numbers"]) == 1 and rep["deliverables/paper/sections/01_introduction.tex"]["typed_numbers"] == []


# ----------------------------------------------------------------------------- without LaTeX
def test_no_latex_is_not_an_error(hub, monkeypatch, capsys):
    from sourcebound import config, deliverable
    from sourcebound.cli import main
    main(["new", "study", "--title", "Study"])
    monkeypatch.chdir(hub / "study")
    monkeypatch.setattr(deliverable.shutil, "which", lambda name: None)      # a machine without TeX
    assert deliverable.tex_tools() == {"latexmk": False, "pdflatex": False, "latexpand": False}
    main(["build"])                                                          # syncs, does not crash
    assert "LaTeX (latexmk) is not installed" in capsys.readouterr().out
    assert (hub / "study" / "deliverables" / "paper" / "generated" / "tikz" / "pipeline.tex").exists()
    with pytest.raises(SystemExit, match="latexpand not found"):
        main(["flatten"])
    (hub.parent / "lake" / "raw").mkdir(parents=True)
    with pytest.raises(SystemExit) as e:
        main(["doctor"])
    assert e.value.code == 0 and "LaTeX             not installed (optional" in capsys.readouterr().out
    main(["handover"])
    doc = json.loads((hub / "study" / "dist" / "handover" / "handover.json").read_text(encoding="utf-8"))
    assert "figure pipeline.pdf is used but not in figures/ (diagram: no PDF: LaTeX is not installed)" in doc["problems"]
    assert config.project().slug == "study"


def test_latex_section_to_markdown():
    from sourcebound.handover import to_markdown, used
    md, left = to_markdown(r"""\section{Results}\label{sec:results}
% a comment
The kurtosis is \result{h1.kurtosis} with a 95\,\% interval \parencite[p.~3]{Cont2001,Fama1965};
\textcite{Mandelbrot1963} found \emph{fat \textbf{tails}} ($p = \result{h2.pvalue}$, $\alpha_1 < 5\%$).
See \cref{fig:tails} and \href{https://example.org/a_b}{the data}.
\begin{figure}[t]
  \centering
  \includegraphics[width=\linewidth]{fig_tails}
  \caption{Density of returns.}\label{fig:tails}
\end{figure}
\begin{table}[t]
  \caption{Large moves}\label{tab:tails}
  \centering
  \input{generated/tables/h2_tails.tex}
  \tablenote{Standardised returns.}
\end{table}
\begin{itemize}
  \item first point
  \item second point
\end{itemize}
\unknowncommand{kept}
""")
    assert md.startswith("# Results {#sec:results}\n")
    assert "is {{result:h1.kurtosis}} with a 95 % interval [@Cont2001; @Fama1965, p. 3];" in md
    assert "@Mandelbrot1963 found *fat **tails*** ($p = {{result:h2.pvalue}}$, $\\alpha_1 < 5\\%$)" in md
    assert "See {{ref:fig:tails}} and [the data](https://example.org/a_b)." in md
    assert "![Density of returns.](figures/fig_tails){#fig:tails}" in md
    assert "{{table:h2_tails}}\n\n: Large moves {#tab:tails}\n\n*Standardised returns.*" in md
    assert "- first point\n- second point" in md
    assert left == ["\\unknowncommand"] and "\\unknowncommand{kept}" in md      # reported, not dropped
    u = used(md)
    assert u["citations"] == ["Cont2001", "Fama1965", "Mandelbrot1963"] and u["tables"] == ["h2_tails"]
    assert u["results"] == ["h1.kurtosis", "h2.pvalue"]


def test_handover_is_complete_and_format_neutral(hub, monkeypatch):
    from sourcebound import results
    from sourcebound.cli import main
    main(["new", "study", "--title", "Study"])
    p = hub / "study"
    monkeypatch.chdir(p)
    monkeypatch.setattr("sys.argv", [str(p / "analysis" / "h1.py")])
    results.record("h1.kurtosis", 4.25, fmt="{:.2f}", hypothesis="H1")
    (p / "tables").mkdir(exist_ok=True)
    (p / "tables" / "h2_tails.csv").write_text("k,n\n3,10\n", encoding="utf-8")
    (p / "figures" / "fig_tails.pdf").write_text("%PDF", encoding="utf-8")
    main(["handover"])
    out = p / "dist" / "handover"
    doc = json.loads((out / "handover.json").read_text(encoding="utf-8"))
    d = doc["deliverables"][0]
    assert (doc["format"], doc["version"], doc["slug"], d["name"]) == ("sourcebound-handover", 1, "study", "paper")
    assert d["title"] == "Study" and d["unconverted"] == []
    files = [s["file"] for s in d["sections"]]
    assert files[0] == "paper/00_abstract.md" and files[-1] == "paper/90_data_appendix.md"
    assert [s["appendix"] for s in d["sections"]][-2:] == [False, True]
    res = next(s for s in d["sections"] if s["file"] == "paper/04_results.md")
    assert "h1.kurtosis" in res["results"] and res["tables"] == ["h2_tails"] and res["figures"] == ["fig_tails.pdf"]
    text = "".join((out / f).read_text(encoding="utf-8") for f in files)
    assert "\\" not in text                               # no LaTeX command left
    assert json.loads((out / "results.json").read_text(encoding="utf-8"))["h1.kurtosis"]["display"] == "4.25"
    for rel in ("tables/h2_tails.csv", "figures/fig_tails.pdf", "evidence/claims.yaml", "README.md"):
        assert (out / rel).exists(), rel
    app = next(s for s in d["sections"] if s["file"] == "paper/90_data_appendix.md")
    assert app["figures"] == ["pipeline.pdf"] and "](figures/pipeline.pdf){#fig:pipeline}" in (out / app["file"]).read_text(encoding="utf-8")
    import shutil
    if shutil.which("pdflatex"):                          # the TikZ diagram as a standalone PDF
        assert (out / "figures" / "pipeline.pdf").read_bytes().startswith(b"%PDF")
        assert (p / "figures" / "tikz" / "pipeline.pdf").exists()
    assert "result h2.count is used but not recorded" in doc["problems"]
    assert not list(out.rglob("*.tex"))


def test_markdown_deliverable(hub, monkeypatch, capsys):
    from sourcebound import config, zotero
    from sourcebound.cli import main
    main(["new", "study", "--title", "Study", "--deliverable", "markdown"])
    p = hub / "study"
    monkeypatch.chdir(p)
    d = p / "deliverables" / "paper"
    assert sorted(x.name for x in d.iterdir()) == ["sections"] and not list(p.rglob("*.cls"))
    assert "format: markdown" in (p / "project.yaml").read_text(encoding="utf-8")
    sec = d / "sections" / "05_conclusion.md"
    sec.write_text(sec.read_text(encoding="utf-8") + "\nNew: {{result:h9.missing}} [@Smith2020new, p. 4].\n")
    assert "Smith2020new" in zotero.cited_keys(config.project())
    with pytest.raises(SystemExit):
        main(["check", "--offline"])
    assert "deliverable uses result h9.missing but it is not recorded" in capsys.readouterr().out
    main(["build"])
    assert "Markdown: nothing to compile" in capsys.readouterr().out
    main(["handover"])
    assert "h9.missing" in (p / "dist" / "handover" / "paper" / "05_conclusion.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- custom sources
def test_datasource_entry_and_archived_documentation(hub, tmp_path, server, capsys):
    from sourcebound import config, sources
    from sourcebound.cli import main
    main(["datasource", "add", "acme_api", "--name", "Acme API", "--url", server, "--auth-env", "ACME_TOKEN",
          "--mcp", "acme"])
    f = config.hub().datasource("acme_api")
    e = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert (e["status"], e["access"], e["auth"]["env"], e["mcp"]) == ("candidate", "api", "ACME_TOKEN", "acme")
    with pytest.raises(SystemExit, match="exists"):
        main(["datasource", "add", "acme_api", "--name", "again"])
    spec = tmp_path / "openapi.json"
    spec.write_text('{"openapi": "3.1.0"}', encoding="utf-8")
    tools = tmp_path / "mcp_tools.json"
    tools.write_text('{"tools": [{"name": "get_prices"}]}', encoding="utf-8")
    main(["datasource", "docs", "acme_api", str(spec), str(tools)])
    main(["datasource", "docs", "acme_api", str(spec)])                      # same content: not stored twice
    assert "already archived" in capsys.readouterr().out
    spec.write_text('{"openapi": "3.1.1"}', encoding="utf-8")
    main(["datasource", "docs", "acme_api", str(spec)])                      # changed: kept next to the old one
    man = sources.docs("acme_api")
    assert [m["origin"] for m in man] == ["file:openapi.json", "file:mcp_tools.json", "file:openapi.json"]
    d = sources.docs_dir("acme_api")
    assert d == f.parent / "acme_api" / "docs" and len(list(d.glob("*openapi.json"))) == 2
    assert (d / man[0]["file"]).read_text(encoding="utf-8") == '{"openapi": "3.1.0"}'        # the first version is untouched
    assert str(tmp_path) not in (d / "manifest.jsonl").read_text(encoding="utf-8")           # no local paths
    main(["datasource", "list"])
    assert "acme_api" in capsys.readouterr().out


def test_token_from_environment_and_docs_by_url(hub, server, monkeypatch):
    from sourcebound import sources
    from sourcebound.fetch import Fetcher
    sources.add("acme_api", name="Acme API", url=server, auth_env="ACME_TOKEN")
    with pytest.raises(RuntimeError, match="ACME_TOKEN"):
        Fetcher("acme_api")
    monkeypatch.setenv("ACME_TOKEN", "s3cret")
    f = Fetcher("acme_api", min_interval=0, jitter=0)
    resp, _ = f.get(server + "/auth")
    assert resp.json() == {"got": "Bearer s3cret"}
    out = sources.archive_docs("acme_api", [server + "/docs/openapi.json"])
    assert out[0]["file"].endswith("_openapi.json") and out[0]["origin"] == server + "/docs/openapi.json"
    archive = "".join(x.read_text(errors="replace") for x in f.dir.rglob("*") if x.is_file() and x.suffix != ".zst")
    assert "s3cret" not in archive                                            # the token is never written


def test_manual_file_and_database_extract(hub, tmp_path, capsys):
    import sqlite3

    from sourcebound import lake, sources
    from sourcebound.cli import main
    from sourcebound.fetch import Fetcher, read_raw
    report = tmp_path / "prices 2026.csv"
    report.write_text("date,id,price\n2026-01-01,a,1.5\n", encoding="utf-8")
    main(["ingest", str(report), "--source", "manual_prices", "--note", "sent by the provider"])
    sha = capsys.readouterr().out.split("raw_ref (sha256): ")[1].split()[0]
    assert read_raw("manual_prices", sha) == report.read_bytes()
    line = Fetcher("manual_prices").manifest()[-1]
    assert (line["url"], line["note"], line["path"].endswith(".csv.zst")) == ("file:prices 2026.csv", "sent by the provider", True)

    db = sqlite3.connect(tmp_path / "warehouse.sqlite")                            # stands in for an internal database
    db.execute("CREATE TABLE prices (date TEXT, id TEXT, price REAL)")
    db.executemany("INSERT INTO prices VALUES (?, ?, ?)", [("2026-01-01", "a", 1.0), ("2026-01-02", "a", 2.0)])
    q = "SELECT date, id, price FROM prices ORDER BY date"
    df, ref = sources.query("warehouse", q, connection=db)
    assert df.height == 2 and Fetcher("warehouse").manifest()[-1]["query"] == q
    again = sources.read_extract("warehouse", ref.sha256)                      # rebuild without the database
    assert again.equals(df)
    table = again.with_columns(pl.col("date").str.to_date(), pl.lit(ref.sha256).alias("raw_ref"))
    lake.write(table.select("date", "id", "price"), "market.prices", mode="upsert")
    assert lake.sql("SELECT count(*) AS n FROM market.prices")["n"][0] == 2
    with pytest.raises(RuntimeError, match="connection_env"):
        sources.query("warehouse", q)


def test_database_by_uri_from_environment(hub, tmp_path, monkeypatch):
    pytest.importorskip("connectorx")                                         # optional: uv sync --extra sql
    import sqlite3

    from sourcebound import sources
    db = sqlite3.connect(tmp_path / "warehouse.sqlite")
    db.execute("CREATE TABLE prices (id TEXT, price REAL)")
    db.execute("INSERT INTO prices VALUES ('a', 1.5)")
    db.commit()
    f = sources.add("warehouse", name="Data warehouse", access="database", connection_env="WAREHOUSE_URI")
    with pytest.raises(RuntimeError, match="WAREHOUSE_URI"):
        sources.query("warehouse", "SELECT id, price FROM prices")
    monkeypatch.setenv("WAREHOUSE_URI", f"sqlite://{tmp_path / 'warehouse.sqlite'}")
    df, ref = sources.query("warehouse", "SELECT id, price FROM prices")
    assert df.to_dicts() == [{"id": "a", "price": 1.5}]
    assert str(tmp_path) not in f.read_text(encoding="utf-8") and sources.read_extract("warehouse", ref.sha256).equals(df)


# ----------------------------------------------------------------------------- paper store
FAKE_CONVERTER = """import sys, pathlib
pdf, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
if b"broken" in pdf.read_bytes():
    sys.exit("cannot read this file")
(out / "paper.md").write_text("<!-- page 1 -->\\nFat tails are common.\\n<!-- page 2 -->\\nKurtosis exceeds three.\\n", encoding="utf-8")
"""


def test_paper_store_and_optional_conversion(hub, tmp_path, monkeypatch, capsys):
    import sys
    import time

    from sourcebound import config, library, zotero
    from sourcebound.cli import main
    main(["new", "study", "--title", "Study", "--empty"])
    monkeypatch.chdir(hub / "study")
    pdfs = tmp_path / "zotero"
    pdfs.mkdir()
    (pdfs / "cont.pdf").write_bytes(b"%PDF cont")
    (pdfs / "bad.pdf").write_bytes(b"%PDF broken")
    in_zotero = {"research/study": ["Cont2001", "Bad1999", "Book1900"]}
    files = {"Cont2001": [{"path": str(pdfs / "cont.pdf")}], "Bad1999": [{"path": str(pdfs / "bad.pdf")}]}
    monkeypatch.setattr(zotero, "collection_keys", lambda path: in_zotero.get(path))
    monkeypatch.setattr(zotero, "attachments", lambda key: files.get(key, []))

    main(["bib", "link"])
    assert "research/study: 3 items" in capsys.readouterr().out
    card = hub / "study" / "project.yaml"
    card.write_text(card.read_text(encoding="utf-8") + "zotero_collections: [research/study, topics/tails]\n")
    with pytest.raises(SystemExit):
        main(["bib", "link"])
    assert "topics/tails: not in Zotero -- create this collection there" in capsys.readouterr().out

    main(["papers", "sync"])                                   # no converter: still useful
    out = capsys.readouterr().out
    assert "2 added, 0 already there" in out and "no PDF in Zotero: Book1900" in out and "no converter configured (optional)" in out
    lib = config.hub().library
    sha = json.loads((lib / "index.json").read_text(encoding="utf-8"))["Cont2001"]
    assert (lib / sha / "paper.pdf").read_bytes() == b"%PDF cont"
    assert str(tmp_path) not in (lib / sha / "source.json").read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="no converter configured"):
        main(["papers", "convert"])

    fake = tmp_path / "fake_converter.py"
    fake.write_text(FAKE_CONVERTER, encoding="utf-8")
    with (hub / "hub.toml").open("a") as fh:
        fh.write("\n[library]\nconverter = '%s %s {pdf} {out}'\n" % (sys.executable, fake))
    config._load_hub.cache_clear()
    main(["papers", "sync"])                                   # starts the conversion in the background
    assert "conversion started in the background" in capsys.readouterr().out
    for _ in range(100):
        if not library.running() and all(r["state"] != "pending" for r in library.status()):
            break
        time.sleep(0.1)
    assert {r["citekeys"][0]: r["state"] for r in library.status()} == {"Cont2001": "converted", "Bad1999": "failed"}
    assert "cannot read this file" in (lib / json.loads((lib / "index.json").read_text(encoding="utf-8"))["Bad1999"] / "convert_error.txt").read_text(encoding="utf-8")
    assert "ok     Cont2001" in (lib / "convert.log").read_text(encoding="utf-8")
    main(["papers", "sync"])                                   # a failed paper is not retried on its own
    assert "0 added, 2 already there" in capsys.readouterr().out
    assert library.convert_in_background() is None
    main(["source", "Cont2001", "--page", "2"])
    out = capsys.readouterr().out
    assert "converted Markdown, page 2" in out and "Kurtosis exceeds three." in out and "Fat tails" not in out
    main(["source", "Cont2001", "--grep", "fat tails"])
    assert "Fat tails are common." in capsys.readouterr().out
    with pytest.raises(SystemExit, match="not in the paper store"):
        main(["source", "Nobody2000"])


def test_collection_includes_sub_collections(hub, monkeypatch):
    from sourcebound import zotero
    tree = [{"id": 1, "name": "My Library", "collections": [
        {"key": "A", "name": "Research", "parentCollection": False},
        {"key": "B", "name": "My Study", "parentCollection": "A"},
        {"key": "C", "name": "Theory", "parentCollection": "B"},
        {"key": "D", "name": "My Study 2", "parentCollection": "A"}]}]
    items = {"Research/My Study": "@article{Cont2001,\n}", "Research/My Study/Theory": "@book{Fama1965,\n}\n@article{Cont2001,\n}",
             "Research/My Study 2": "@article{Other2020,\n}", "Research": ""}
    monkeypatch.setattr(zotero, "_rpc", lambda method, params, **kw: tree)

    class Reply:
        def __init__(self, text):
            self.status_code, self.text = (200, text) if text is not None else (404, "")

        def raise_for_status(self):
            pass
    from urllib.parse import unquote
    monkeypatch.setattr(zotero.httpx, "get", lambda url, **kw: Reply(items.get(unquote(url.split("?/1/")[1]).removesuffix(".biblatex"))))
    assert zotero.collection_keys("research/my study") == ["Cont2001", "Fama1965"]     # with its sub-collection, any case
    assert zotero.collection_keys("Research") == ["Cont2001", "Fama1965", "Other2020"]
    assert zotero.collection_keys("research/missing") is None


# ----------------------------------------------------------------------------- without make (Windows)
def test_install_and_run_without_make(hub, tmp_path, monkeypatch, capfd):
    from sourcebound import library
    from sourcebound.cli import main
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    main(["install", "--bin", str(tmp_path / "bin")])
    claude = tmp_path / "home" / ".claude"
    assert (claude / "skills" / "research-study" / "SKILL.md").exists()
    assert (claude / "agents" / "sb-writer.md").exists()
    assert (tmp_path / "bin" / "sb").exists()
    main(["install", "agents"])                                              # again: replaces, does not fail

    p = hub / "study"
    (p / "analysis").mkdir(parents=True)
    (p / "project.yaml").write_text("slug: study\ntitle: Study\n", encoding="utf-8")
    (p / "analysis" / "a1.py").write_text("print('first step')\n", encoding="utf-8")
    (p / "analysis" / "a2.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    monkeypatch.chdir(p)
    with pytest.raises(SystemExit) as e:                                     # stops at the first failing step
        main(["run", "analysis", "figures"])
    out = capfd.readouterr().out
    assert e.value.code == 3 and "== analysis/a1.py" in out and "first step" in out and "figures" not in out

    assert library._alive(os.getpid()) and not library._alive(2 ** 22 + 12345)


# ----------------------------------------------------------------------------- integrity of the record
def _offline(hub):
    """No Zotero in these tests, whatever runs on the machine."""
    from sourcebound import config
    with (hub / "hub.toml").open("a") as fh:
        fh.write("\n[zotero]\nurl = 'http://127.0.0.1:9'\n")
    config._load_hub.cache_clear()


def test_parallel_agents_do_not_lose_results_or_share_source_ids(hub):
    import subprocess
    import sys

    from sourcebound import config, results
    p = hub / "study"
    (p / "evidence").mkdir(parents=True)
    (p / "project.yaml").write_text("slug: study\ntitle: Study\n", encoding="utf-8")
    code = ("import sys\nfrom sourcebound import ledger, results\n"
            "for j in range(15): results.record(f'p{sys.argv[1]}.r{j}', j)\n"
            "print(ledger.add_source({'title': 't', 'url': 'https://example.org', 'accessed': '2026-01-01'}))\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(i)], cwd=p, stdout=subprocess.PIPE, text=True) for i in range(6)]
    ids = [x.communicate()[0].strip() for x in procs]
    assert all(x.returncode == 0 for x in procs)
    assert len(results.load(config.project(p))) == 90
    assert sorted(ids) == [f"W-000{n}" for n in range(1, 7)]


def test_freeze_protects_hypotheses(hub):
    from sourcebound import config, ledger
    from sourcebound.cli import main
    main(["new", "study", "--title", "Study"])
    p = config.project(hub / "study")
    f = p.root / "hypotheses.yaml"
    frozen = lambda: [e for e in ledger.check(p, resolve_citekeys=False)[0] if "freeze of" in e]
    assert "hashes" in ledger.load(p)["hdoc"]["frozen"] and frozen() == []
    with pytest.raises(ValueError, match="already frozen"):
        ledger.freeze(p)
    doc = yaml.safe_load(f.read_text(encoding="utf-8"))
    doc["hypotheses"][0]["status"] = "refuted"                               # the outcome may change ...
    f.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    assert frozen() == []
    doc["hypotheses"][1]["decision_rule"] = "whatever fits the data"         # ... the registered rule may not
    doc["hypotheses"].append({**doc["hypotheses"][0], "id": "H3"})           # nor may a new one be tested unannounced
    f.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    assert ["H2" in e or "H3" in e for e in frozen()] == [True, True]
    with pytest.raises(ValueError, match="H2, H3"):
        ledger.freeze(p, amend=True)                                         # an amendment must say why
    doc["hypotheses"][2]["exploratory"] = True
    doc["amendments"] = [{"date": "2026-01-02", "hypotheses": ["H2", "H3"], "reason": "the registered rule was ambiguous"}]
    f.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    ledger.freeze(p, amend=True)
    fr = ledger.load(p)["hdoc"]["frozen"]
    assert frozen() == [] and fr["amendments"] == 1 and "amended" in fr and set(fr["hashes"]) == {"H1", "H2", "H3"}


def test_check_reports_provenance_and_typed_numbers(hub, capsys, monkeypatch):
    from sourcebound import config, results
    from sourcebound.cli import main
    _offline(hub)
    main(["new", "study", "--title", "Study"])
    p = config.project(hub / "study")
    prov = lambda **kw: {"value": 1, "display": "1", "provenance": {"script": "analysis/h1_fat_tails.py", "git": "abc1234",
                                                                    "data": {"market.prices": 3}, **kw}}
    results.save({"ok.a": prov(), "ghost.b": prov(script="-c"), "dirty.c": prov(git="abc1234+dirty"),
                  "none.d": prov(git=None), "old.e": prov(data={"market.prices": 2}), "bare.f": prov(data={})}, p)
    errs, warns = results.problems(p)
    text = "\n".join(warns)
    assert len(errs) == 1 and "ghost.b" in errs[0]
    assert all(x in text for x in ("uncommitted analysis code (dirty.c)", "not tied to a commit (none.d)",
                                   "different snapshots of market.prices", "no lake table (bare.f)"))
    assert len(results.problems(p, strict=True)[0]) == 4                     # the publication gate refuses them
    sec = p.root / "deliverables" / "paper" / "sections" / "05_conclusion.tex"
    sec.write_text(sec.read_text(encoding="utf-8") + "The effect is 12.7 percent at the 5\\,\\% level.\n", encoding="utf-8")
    monkeypatch.chdir(p.root)
    with pytest.raises(SystemExit):
        main(["check", "--offline"])
    out = capsys.readouterr().out
    assert "05_conclusion.tex: 1 lines with a number typed by hand" in out and "01_introduction.tex" not in out


def test_run_rebuilds_results_and_one_script_merges(hub, monkeypatch):
    from sourcebound import config, results
    from sourcebound.cli import main
    p = hub / "study"
    (p / "analysis").mkdir(parents=True)
    (p / "project.yaml").write_text("slug: study\ntitle: Study\n", encoding="utf-8")
    (p / "analysis" / "a1.py").write_text("from sourcebound import results\nresults.record('a.one', 1)\n", encoding="utf-8")
    monkeypatch.chdir(p)
    proj = config.project(p)
    results.save({"stale.key": {"value": 9, "display": "9", "provenance": {"script": "analysis/gone.py"}}}, proj)
    main(["run", "analysis/a1.py"])                                           # an analyst's own script: merged
    assert set(results.load(proj)) == {"a.one", "stale.key"}
    main(["run", "analysis"])                                                 # all scripts: fresh results
    assert set(results.load(proj)) == {"a.one"}
    (p / "analysis" / "a2.py").write_text("raise SystemExit(2)\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["run", "analysis"])
    assert set(results.load(proj)) == {"a.one"}                               # a failed run keeps the earlier results
    with pytest.raises(SystemExit, match="unknown step"):
        main(["run", "nonsense"])


def test_publish_bundle_and_gates(hub, monkeypatch):
    from sourcebound import config, publish
    from sourcebound.cli import main
    _offline(hub)
    main(["new", "study", "--title", "Study", "--deliverable", "markdown"])
    p = hub / "study"
    card = p / "project.yaml"
    card.write_text(card.read_text(encoding="utf-8").replace("data: [market.ecb_fx_daily]", "data: [market.prices]")
                    + "data_root: ../somewhere/private\n", encoding="utf-8")
    monkeypatch.chdir(p)
    rep = publish.build(config.project(p))
    out = p / "dist" / "public"
    public = yaml.safe_load((out / "project.yaml").read_text(encoding="utf-8"))
    assert set(public) <= {"slug", "title", "lang", "created", "reads", "owns"}          # no owner, no local paths
    assert (out / "uv.lock").exists() and not (out / "study.pdf").exists()
    text = (out / "study.md").read_text(encoding="utf-8")                                # Markdown deliverable, no PDF
    assert text.startswith("# Study") and "[@" in text and "no PDF" in "\n".join(rep["warnings"])
    errors = "\n".join(rep["errors"])
    assert "market.prices: the contract states no licence" in errors
    assert not list(out.rglob("*.bib")) and not list(out.rglob("*.tex"))
    with pytest.raises(SystemExit, match="user's decision"):                             # never for an agent
        main(["unblock", "web"])
    main(["new", "latex", "--title", "Latex"])
    monkeypatch.chdir(hub / "latex")
    assert "deliverable PDF missing" in "\n".join(publish.build(config.project(hub / "latex"))["errors"])


def test_bib_sync_keeps_the_file_without_zotero(hub):
    from sourcebound import config, zotero
    _offline(hub)
    p = hub / "study"
    sec = p / "deliverables" / "paper" / "sections"
    sec.mkdir(parents=True)
    (p / "project.yaml").write_text("slug: study\ntitle: Study\n", encoding="utf-8")
    (sec / "01_text.md").write_text("Fat tails are common [@Cont2001].\n", encoding="utf-8")
    bib = p / "deliverables" / "paper" / "references.bib"
    bib.write_text("@article{Cont2001,\n  title = {Empirical properties}\n}\n", encoding="utf-8")
    proj = config.project(p)
    assert zotero.sync(proj) == ([bib], [], False) and "Empirical properties" in bib.read_text(encoding="utf-8")
    (sec / "01_text.md").write_text("Fat tails are common [@Cont2001; @Other1999].\n", encoding="utf-8")
    assert zotero.sync(proj)[1:] == (["Other1999"], False) and "Empirical properties" in bib.read_text(encoding="utf-8")


def test_token_stays_with_its_host_and_requests_are_spaced_across_processes(hub, server, monkeypatch):
    import time

    from sourcebound import fetch, sources
    sources.add("acme_api", name="Acme API", url=server, auth_env="ACME_TOKEN")
    monkeypatch.setenv("ACME_TOKEN", "s3cret")
    other = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    f = fetch.Fetcher("acme_api", min_interval=0, jitter=0)
    assert f.get(server + "/auth")[0].json() == {"got": "Bearer s3cret"}
    assert f.get(f"http://127.0.0.1:{other.server_address[1]}/auth")[0].json() == {"got": None}
    entry = f.h.datasource("acme_api")                                        # a header httpx would not strip itself
    entry.write_text(entry.read_text(encoding="utf-8").replace("header: Authorization", "header: X-Api-Key"), encoding="utf-8")
    g = fetch.Fetcher("acme_api", min_interval=0, jitter=0)
    assert g.get(server + "/auth?own")[0].json() == {"got": "Bearer s3cret"}
    assert g.get(f"{server}/to/{other.server_address[1]}")[0].json() == {"got": None}      # not on a redirect either
    with pytest.raises(fetch.Blocked):                                        # a refusal after a redirect stops the host
        g.get(f"{server}/to/{other.server_address[1]}/block")                 # that refused, not the one that redirected
    assert list(fetch.blocked("acme_api")) == [f"127.0.0.1_{other.server_address[1]}"]
    assert g.get(server + "/auth?still")[0].status_code == 200
    other.shutdown()
    a, b = fetch.Fetcher("one", min_interval=0.4, jitter=0), fetch.Fetcher("two", min_interval=0.4, jitter=0)
    a._wait("example.org")
    t = time.monotonic()
    b._wait("example.org")                                                    # another source, same host: the time is a file
    assert time.monotonic() - t > 0.25 and (a.h.raw_root / ".hosts" / "example.org.last").exists()
    assert fetch._challenge(b"<html>solve this captcha</html>")              # a short page that is only the challenge
    assert not fetch._challenge(b"<html>comment form with captcha" + b"x" * 20000)
    assert fetch._challenge(b"<html>cf-challenge" + b"x" * 20000)


# ----------------------------------------------------------------------------- the web view
def test_latex_constructs_reach_the_handover_as_markdown():
    from sourcebound.handover import macros, to_markdown
    defs = macros(r"\newcommand\sbcmd[1]{\texttt{#1}} \newcommand{\tool}{Sourcebound}")
    assert defs == {"sbcmd": (1, r"\texttt{#1}"), "tool": (0, "Sourcebound")}
    md, left = to_markdown(r"""Run \sbcmd{sb check} in \tool. ``Quoted'' and \LaTeX\ \ldots
\begin{description}[style=nextline]
  \item[P1 First.] Text of
    the first.
  \item[P2 Second.] More.
\end{description}
\begin{table}\caption{Kinds}\label{tab:kinds}
\begin{tabular}{@{}l>{\raggedright}p{0.3\linewidth}@{}}
  \toprule Kind & Example \\ \midrule
  Result & \texttt{R:h1.x} \\
  Data & a | b \\ \bottomrule
\end{tabular}\end{table}
\begin{lstlisting}
name: analyst  % not a comment
  -- kept as written
\end{lstlisting}
""", defs)
    assert left == []
    assert "Run `sb check` in Sourcebound. “Quoted” and LaTeX …" in md
    assert "- **P1 First.** Text of the first.\n- **P2 Second.** More." in md
    assert ": Kinds {#tab:kinds}" in md
    assert "| Kind | Example |\n| --- | --- |\n| Result | `R:h1.x` |\n| Data | a \\| b |" in md
    assert "```\nname: analyst  % not a comment\n  -- kept as written\n```" in md


def test_database_connections_are_described_tested_and_read_only(tmp_path, monkeypatch):
    import sqlite3

    import duckdb

    from sourcebound import config, connections, databases, sources
    from sourcebound.cli import main
    _init(tmp_path)
    db = tmp_path / "shop.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE prices (id INTEGER, price REAL)")
    con.executemany("INSERT INTO prices VALUES (?, ?)", [(1, 9.5), (2, 12.0)])
    con.commit()
    con.close()
    # created field by field, as the web view's form does it
    with pytest.raises(databases.SpecError) as err:
        databases.save("shop", name="Shop", spec={"driver": "mssql", "server": "bad host", "port": "x", "auth": "sql"})
    assert set(err.value.errors) == {"server", "port", "database", "user"}
    made = databases.save("shop", name="Shop", spec={"driver": "sqlite", "path": str(db)})
    assert made["created"] and made["before"] is None
    entry = sources.entry("shop")
    assert entry["access"] == "database" and entry["database"]["driver"] == "sqlite" and "password" not in str(entry)
    assert databases.test("shop") == {**databases.last_test("shop"), "status": "ok"}
    assert connections.sql("shop", "SELECT price FROM prices ORDER BY id")["rows"] == [[9.5], [12.0]]
    with pytest.raises(ValueError):
        connections.sql("shop", "DELETE FROM prices")
    t = next(x for x in connections.targets() if x["id"] == "shop")
    assert t["ready"] and t["tested"] == "ok"
    # a DuckDB file, changed through the command line
    duck = tmp_path / "w.duckdb"
    c = duckdb.connect(str(duck))
    c.execute("CREATE TABLE t AS SELECT 42 AS x")
    c.close()
    main(["datasource", "set", "shop", "--driver", "duckdb", "--path", str(duck)])
    assert connections.sql("shop", "SELECT x FROM t")["rows"] == [[42]]
    f = config.hub().datasource("shop")
    assert f.read_text(encoding="utf-8").startswith("# Data source register entry")     # the rest of the entry is kept
    # client-server URIs: the password from the session, else from the variable the entry names
    spec = databases.check({"driver": "mssql", "server": "sql-01", "database": "Research", "auth": "sql",
                            "user": "ana", "password_env": "SHOP_PW", "trust_server_certificate": True})
    with pytest.raises(RuntimeError, match="SHOP_PW"):
        databases.uri("wh", spec)
    monkeypatch.setenv("SHOP_PW", "p@ss:w/rd")
    assert databases.uri("wh", spec) == "mssql://ana:p%40ss%3Aw%2Frd@sql-01:1433/Research?encrypt=true&trust_server_certificate=true"
    databases.remember("wh", "session")
    assert "ana:session@" in databases.uri("wh", spec)
    databases.forget("wh")
    win = databases.check({"driver": "mssql", "server": "sql-01", "database": "R", "auth": "windows", "user": "ignored"})
    assert databases.uri("wh", win) == "mssql://sql-01:1433/R?trusted_connection=true&encrypt=true"
    pg = databases.check({"driver": "postgresql", "server": "db", "database": "d", "auth": "none", "ssl_mode": "require"})
    assert databases.uri("pg", pg) == "postgresql://db:5432/d?sslmode=require"
    with pytest.raises(databases.SpecError):
        databases.check({"driver": "postgresql", "server": "db", "database": "d", "auth": "windows"})
    # undo: remove puts nothing back by itself, restore does; an entry with extracts stays
    gone = databases.remove("shop")
    assert sources.entry("shop") == {}
    databases.restore("shop", gone["before"])
    assert sources.entry("shop")["database"]["driver"] == "duckdb"
    (config.hub().raw_root / "shop").mkdir(parents=True)
    with pytest.raises(PermissionError):
        databases.remove("shop")


def test_update_keeps_the_installed_extras_and_refuses_over_changes(tmp_path, monkeypatch, capsys):
    import subprocess

    from sourcebound import update
    home = tmp_path / "checkout"
    (home / "frontend" / "dist").mkdir(parents=True)
    (home / "frontend" / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (home / "pyproject.toml").write_text('[project]\nname = "x"\n[project.optional-dependencies]\n'
                                         'yaml = ["PyYAML>=6"]\nmissing = ["no-such-package-xyz"]\nboth = ["PyYAML", "no-such-package-xyz"]\n',
                                         encoding="utf-8")
    assert update.extras(home / "pyproject.toml")["both"] == ["PyYAML", "no-such-package-xyz"]
    assert update.installed_extras(home / "pyproject.toml") == ["yaml"]          # all of its packages, or it does not count
    steps = [what for what, _ in update.plan(home, ["yaml"])]
    assert steps == ["pull the checkout", "install the packages (extras: yaml)", "install sb, playbooks and subagents",
                     "build the web view", "check the installation"]
    sync = dict(update.plan(home, ["yaml"]))["install the packages (extras: yaml)"]
    assert sync[1:] == ["sync", "--extra", "yaml"]                               # run inside the checkout
    assert "build the web view" not in dict(update.plan(home, [], frontend=False))
    with pytest.raises(SystemExit, match="no extra nope"):
        update.run(home, add=["nope"], dry_run=True)
    git = lambda *a: subprocess.run(["git", "-C", str(home), "-c", "user.name=t", "-c", "user.email=t@example.org", *a],
                                    check=True, capture_output=True)
    git("init", "-q")
    git("add", "pyproject.toml")
    git("commit", "-q", "-m", "first")
    assert update.run(home, add=[], dry_run=True) == 0 and "== pull the checkout" in capsys.readouterr().out
    (home / "pyproject.toml").write_text((home / "pyproject.toml").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="uncommitted changes"):
        update.run(home, add=[], dry_run=True)


def test_web_view_starts_once_per_port(monkeypatch, capsys):
    from sourcebound import ui
    first = ui.Server(("127.0.0.1", 0), ui.Handler)
    try:
        port = first.server_address[1]
        with pytest.raises(OSError):                               # Windows too: no second listener on the port
            ui.Server(("127.0.0.1", port), ui.Handler)
        opened = []
        monkeypatch.setattr(ui, "running", lambda p: {"name": "sourcebound-ui"})
        monkeypatch.setattr("webbrowser.open", opened.append)
        ui.serve(port, bridge=False)                               # the desktop icon twice: the first one is used
        assert opened == [f"http://127.0.0.1:{port}"] and "already running" in capsys.readouterr().out
    finally:
        first.server_close()


def test_markdown_reads_tables_layout_and_boxes_without_latex():
    from sourcebound.handover import macros, to_markdown
    defs = macros(r"\newcommand\keyfig[2]{\textbf{\large #1}\par\smallskip{\footnotesize #2}}")
    md, left = to_markdown(r"""\paragraph{Short answer.} Text.
\begin{table}[h]
\centering
\caption{Who offers what: group \texttimes{} product}
\label{tab:who}
\small
\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}p{4cm}*{2}{>{\centering\arraybackslash}X}@{}}
\toprule
Group & Stan\-dard & Free \\
\midrule
Banks & yes & -- \\
\bottomrule
\end{tabularx}
\tablenote{{\raggedright\footnotesize Own assignment.}}
\end{table}
\begin{tabularx}{\linewidth}{XX}
\keyfig{1.0\,\%}{cost cap} & \keyfig{\result{a.b}\,EUR}{grant} \\
\end{tabularx}
\begin{note}{For providers.}
\vspace{3pt}Three ways:
\begin{enumerate}
\item One.
\end{enumerate}
\end{note}
""", defs)
    assert left == []
    assert md.startswith("**Short answer.** Text.")
    assert ": Who offers what: group × product {#tab:who}" in md
    assert "| Group | Standard | Free |\n| --- | --- | --- |\n| Banks | yes | – |\n\n*Own assignment.*" in md
    assert "| **1.0 %** cost cap | **{{result:a.b}} EUR** grant |" in md
    assert "> **For providers.**\n>\n> Three ways:\n>\n> 1. One." in md


def test_desktop_icon_starts_the_web_view(tmp_path):
    from sourcebound import shortcut
    assert shortcut.available()                                    # this checkout has the frontend
    path = shortcut.create(tmp_path / "Desktop")
    assert path.exists() and path.parent == tmp_path / "Desktop"
    if os.name == "nt":
        assert path.suffix == ".lnk"
    else:
        text = path.read_text(encoding="utf-8")
        assert str(shortcut.sb_executable()) in text and " ui" in text and os.access(path, os.X_OK)
    assert shortcut.create(tmp_path / "Desktop") == path          # a second run replaces it


def test_find_up_skips_a_folder_it_may_not_read(tmp_path, monkeypatch):
    from sourcebound import config
    (tmp_path / "hub.toml").write_text("", encoding="utf-8")
    start = tmp_path / "a" / "b"
    start.mkdir(parents=True)
    exists = Path.exists
    def guarded(p, *args, **kw):            # like the root of a network share: access denied
        if p.parent == tmp_path / "a":
            raise PermissionError(13, "Access is denied", str(p))
        return exists(p, *args, **kw)
    monkeypatch.setattr(Path, "exists", guarded)
    assert config.find_up("hub.toml", start) == tmp_path.resolve()


def test_web_view_finds_node_on_the_path_or_in_wsl(tmp_path, monkeypatch):
    from sourcebound import ui
    found = {"npm": "/usr/bin/npm"}
    monkeypatch.setattr(ui.shutil, "which", lambda name: found.get(name))
    assert ui._node_tool("npm", tmp_path) == ["/usr/bin/npm"]
    found = {"wsl.exe": r"C:\Windows\System32\wsl.exe"}            # Windows without Node, but with WSL
    monkeypatch.setattr(ui.sys, "platform", "win32")
    cmd = ui._node_tool("npm", tmp_path)
    assert ui._in_wsl(cmd) and cmd[-1] == str(tmp_path) and cmd[-3].endswith('&& npm "$@"')
    monkeypatch.setattr(ui.sys, "platform", "linux")               # elsewhere there is no fallback
    assert ui._node_tool("npm", tmp_path) is None


def test_web_view_lists_projects_of_further_folders(hub, tmp_path, monkeypatch):
    import dataclasses
    from sourcebound import config, ui
    from sourcebound.cli import main
    main(["new", "study", "--title", "A Study"])
    elsewhere = tmp_path / "elsewhere"                      # a folder of projects, and a project on its own
    for d, slug in ((elsewhere / "desk-a", "desk_a"), (tmp_path / "single", "single")):
        d.mkdir(parents=True)
        (d / "project.yaml").write_text(f"slug: {slug}\nkind: desk\n", encoding="utf-8")
    real = config.hub()
    monkeypatch.setattr(ui.config, "hub", lambda: dataclasses.replace(real, projects_also=(elsewhere, tmp_path / "single")))
    assert set(ui.project_roots()) == {"study", "desk_a", "single"}


def test_web_view_reads_the_project_files(hub, monkeypatch):
    from sourcebound import ui
    from sourcebound.cli import main
    main(["new", "study", "--title", "A Study"])
    main(["new", "other", "--title", "Other"])
    assert list(ui.project_roots()) == ["other", "study"]
    monkeypatch.chdir(hub / "study")
    row = ui.summary("study", hub / "study")
    # the template is a worked example: past the brief, frozen, not published
    assert (row["title"], row["phase"], [g["passed"] for g in row["gates"]]) == ("A Study", "deliverables", [True, True, False])
    d = ui.detail("study")
    assert {h["registration"] for h in d["hypothesis_list"]} == {"unchanged"}
    hf = hub / "study" / "hypotheses.yaml"                   # a prediction edited after the freeze shows as changed
    doc = yaml.safe_load(hf.read_text(encoding="utf-8"))
    doc["hypotheses"][0]["prediction"] += " Or not."
    hf.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    assert [h["registration"] for h in ui.detail("study")["hypothesis_list"]][:2] == ["changed", "unchanged"]
    assert d["hypotheses"]["total"] == len(d["hypothesis_list"]) > 0 and d["claims"]["total"] == len(d["claim_list"])
    assert d["handover"] == {"built": False} and ui.handover("study") == {"built": False}
    assert d["deliverable_folders"][0]["name"] == "paper" and {"path": "research/brief.md", "group": "Research"}.items() <= d["documents"][0].items()
    assert d["deliverable_folders"][0]["renders"] == []
    from sourcebound import config as cfg, render
    render.render("deliverables/paper", "markdown", project=cfg.project(hub / "study"))       # another format of the paper
    shown = ui.detail("study")["deliverable_folders"][0]["renders"]
    assert [(r["template"], r["kind"], r["stale"]) for r in shown] == [("markdown", "markdown", [])]
    assert shown[0]["files"] and all(x.startswith("dist/render/paper/markdown/") for x in shown[0]["files"])
    assert "brief" in ui.text_file("study", "research/brief.md")["text"].lower()
    for path in ("../other/project.yaml", "deliverables/paper/main.tex", "research/missing.md", ".git/config"):
        with pytest.raises(ui.NotFound):
            ui.text_file("study", path)
    with pytest.raises(ui.NotFound):
        ui.detail("nothing")
    # the handover is what the reader shows: prose, tables and what the prose refers to
    (hub / "study" / "tables").mkdir(exist_ok=True)
    (hub / "study" / "tables" / "t1.csv").write_text("Name,Share\n\\texttt{a},1.0--1.5\n", encoding="utf-8")
    out = ui.run("study", "handover")
    assert out["exit_code"] == 0 and out["command"] == "sb handover"
    h = ui.handover("study")
    assert h["built"] and not h["stale"] and h["handover"]["deliverables"][0]["name"] == "paper"
    assert set(h["sections"]) == {s["file"] for s in h["handover"]["deliverables"][0]["sections"]}
    assert h["tables"]["t1"] == {"columns": ["Name", "Share"], "rows": [["`a`", "1.0–1.5"]]}
    assert ui.detail("study")["handover"]["built"]
    with pytest.raises(ValueError, match="runs only"):
        ui.run("study", "publish --push")
    # the VS Code workspace: every project and the data root, with the usual steps as tasks
    f = ui.write_workspace()
    ws = json.loads(f.read_text(encoding="utf-8"))
    assert f == hub / "research.code-workspace"
    assert [x["name"] for x in ws["folders"]][:2] == ["study", "other"] and ws["folders"][-1]["name"] == "data root"
    assert "sb check" in [t["command"] for t in ws["tasks"]["tasks"]]


def test_bibliography_fields_for_the_reader():
    from sourcebound.ui import _bib
    bib = _bib("""@article{Cont2001Empirical, title={Empirical properties of asset returns: {S}tylized facts}, volume={1},
  journal={Quantitative Finance}, author={Cont, R.}, year={2001}, pages={223–236} }

@online{W-0003,
  author = {{DuckDB Foundation}},
  title = {DuckLake},
  url = {https://ducklake.select/},
  date = {2025-05-27}
}""")
    assert bib["Cont2001Empirical"] == {"type": "article", "year": "2001", "author": "Cont, R.", "journal": "Quantitative Finance",
                                        "title": "Empirical properties of asset returns: Stylized facts", "volume": "1", "pages": "223–236"}
    assert bib["W-0003"]["author"] == "DuckDB Foundation" and bib["W-0003"]["year"] == "2025"


def test_web_view_answers_this_machine_only(hub, monkeypatch):
    import urllib.error
    import urllib.request

    from sourcebound import ui
    from sourcebound.cli import main
    main(["new", "study", "--title", "A Study"])
    server = ui.ThreadingHTTPServer(("127.0.0.1", 0), ui.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, *, data=None, headers=None):
        req = urllib.request.Request(base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        assert call("/api/health")[1]["name"] == "sourcebound-ui"
        assert [p["id"] for p in call("/api/projects")[1]["projects"]] == ["study"]
        assert call("/api/projects/study/file?path=../hub.toml")[0] == 404
        assert call("/api/projects", headers={"Origin": "https://example.org"})[0] == 403          # another site
        assert call("/api/projects", headers={"Host": "attacker.example:80"})[0] == 403            # DNS rebinding
        assert call("/api/projects", headers={"Origin": "http://localhost:5200"})[0] == 200        # the dev server
        assert call("/api/workspace", data=b"{}", headers={"Content-Type": "text/plain"})[0] == 415  # a plain form post
        status, body = call("/api/projects/study/run", data=b'{"command": "freeze"}', headers={"Content-Type": "application/json"})
        assert status == 400 and "runs only" in body["error"]
        status, body = call("/api/projects/study/notes", data=b'{"op": "add", "title": "A note"}', headers={"Content-Type": "application/json"})
        assert status == 200 and body["note"]["id"] == "N001"
        assert call("/api/projects/study")[1]["notes"][0]["title"] == "A note"
    finally:
        server.shutdown()
        server.server_close()


def test_deliverable_notes(hub, monkeypatch, capsys):
    from sourcebound import config, notes
    from sourcebound.cli import main
    main(["new", "study", "--title", "A Study"])
    monkeypatch.chdir(hub / "study")
    main(["note", "add", "Two-page", "note", "--kind", "note", "--prompt", "Write it."])
    main(["note", "add", "Infographic of H2", "--status", "planned"])
    p = config.project()
    assert [(n["id"], n["title"], n["status"]) for n in notes.load(p)] == [("N001", "Two-page note", "idea"), ("N002", "Infographic of H2", "planned")]
    main(["note", "set", "N001", "--status", "drafting", "--title", "Note for practitioners"])
    before, after = notes.update("N002", p, text="Square format")
    assert (before["text"], after["text"], after["status"]) == ("", "Square format", "planned")
    removed = notes.remove("N001", p)
    assert removed["status"] == "drafting" and [n["id"] for n in notes.load(p)] == ["N002"]
    notes.put(removed, p)                                    # undo
    assert [n["title"] for n in notes.load(p)] == ["Note for practitioners", "Infographic of H2"]
    assert notes.add(p, title="Third")["id"] == "N003"
    capsys.readouterr()
    main(["note", "list"])
    assert "N001  drafting note         Note for practitioners" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="status must be one of"):
        main(["note", "set", "N002", "--status", "finished"])
    with pytest.raises(SystemExit, match="no note N009"):
        main(["note", "rm", "N009"])
    from sourcebound import deliverable
    assert [d.name for d in deliverable.folders(p, markdown=True)] == ["paper"]      # the notes file is not a deliverable


def test_hook_events_become_activity_lines(hub, monkeypatch, tmp_path):
    import io

    from sourcebound import activity
    from sourcebound.cli import main
    main(["new", "study", "--title", "A Study"])
    cwd = str(hub / "study" / "analysis")
    activity.record({"hook_event_name": "PreToolUse", "session_id": "0123456789abcdef", "cwd": cwd, "tool_name": "Agent",
                     "tool_input": {"subagent_type": "verifier", "description": "Check section 5", "prompt": "the whole secret brief"}})
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"hook_event_name": "PreToolUse", "session_id": "0123456789abcdef", "cwd": cwd, "agent_type": "verifier",
         "tool_name": "Bash", "tool_input": {"command": "sb source W-0001 --grep " + "x" * 400}})))
    main(["hook"])
    for bad in ("not json", "{}", "[1, 2]"):                 # a hook must never fail the tool call it observes
        monkeypatch.setattr("sys.stdin", io.StringIO(bad))
        main(["hook"])
    log = hub.parent / "lake" / "activity" / "events.jsonl"
    assert activity.log_path() == log and "secret" not in log.read_text(encoding="utf-8")
    newest, first = activity.tail()
    assert (first["event"], first["session"], first["project"], first["agent"], first["tool"], first["summary"]) == (
        "PreToolUse", "01234567", "study", "verifier", "Agent", "Check section 5")
    assert newest["tool"] == "Bash" and len(newest["summary"]) == 200
    # the hooks go into a Claude Code settings file once, next to what is there
    settings = tmp_path / "claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(sb:*)"]}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}), encoding="utf-8")
    assert activity.install(settings) and not activity.install(settings)
    doc = json.loads(settings.read_text(encoding="utf-8"))
    assert doc["permissions"] == {"allow": ["Bash(sb:*)"]} and sorted(doc["hooks"]) == ["PreToolUse", "SessionStart", "Stop", "SubagentStop"]
    assert [h["command"] for g in doc["hooks"]["Stop"] for h in g["hooks"]] == ["say done", "sb hook"]


# ----------------------------------------------------------------------------- beyond one study
@pytest.fixture()
def desk(hub, monkeypatch):
    """A desk project inside the test hub, as the working directory."""
    from sourcebound.cli import main
    main(["new", "topic", "--title", "A Topic", "--kind", "desk", "--lang", "de"])
    monkeypatch.chdir(hub / "topic")
    return hub / "topic"


def test_desk_is_a_project_without_paper_or_hypotheses(desk, capsys):
    from sourcebound import config, ledger, ui
    from sourcebound.cli import main
    p = config.project()
    assert (p.meta["kind"], p.meta["phase"], p.lang) == ("desk", "ongoing", "de")
    assert not (desk / "hypotheses.yaml").exists() and not (desk / "deliverables").exists()
    assert ledger.check(p, resolve_citekeys=False) == ([], [])
    main(["status"])
    assert "topic: A Topic" in capsys.readouterr().out
    row = ui.summary("topic", desk)
    assert (row["kind"], row["pieces"], [g["passed"] for g in row["gates"]]) == ("desk", {"total": 0, "by_status": {}}, [False] * 3)


def test_a_piece_from_a_local_document_to_rendered_text(desk, tmp_path, capsys):
    from sourcebound import config, pieces, render
    from sourcebound.cli import main
    report = tmp_path / "Report 2024.txt"
    report.write_text("In June 2024 about 20 % of trading days saw a large move.\n", encoding="utf-8")
    main(["doc", str(report), "--title", "Report on returns", "--publisher", "Example Institute", "--date", "2024-11-18"])
    assert "W-0001  Report on returns (Example Institute)" in capsys.readouterr().out
    main(["source", "W-0001", "--grep", "20 %"])                  # the archived copy is what a verifier reads
    assert "about 20 % of trading days" in capsys.readouterr().out
    main(["piece", "add", "Grosse", "Bewegungen", "--kind", "post", "--id", "p1", "--template", "text"])
    p = config.project()
    (desk / "pieces" / "p1" / "text.md").write_text(
        "# Titel\n\nRund 20 % bewegten sich stark [@W-0001, S. 3]. Laut @W-0001 sind es **viele**; siehe {{result:x.n}} und [@W-0009].\n", encoding="utf-8")
    errs, warns = pieces.check("p1", p)
    assert errs == ["result x.n is used but not recorded", "source W-0009 is cited but not in evidence/sources.yaml (sb snap URL, or sb doc FILE)"]
    assert not any("typed by hand" in w for w in warns)         # the number is cited in its sentence
    assert any("quoted with a citation in the same sentence, lines 3 (20 %)" in i for i in pieces.findings("p1", p)["info"])
    with pytest.raises(SystemExit):
        main(["piece", "check", "p1"])
    from sourcebound import results
    (desk / "analysis" / "a.py").write_text("", encoding="utf-8")
    results.save({"x.n": {"value": 7, "display": "7", "unit": None, "provenance": {"script": "analysis/a.py"}}}, p)
    (desk / "pieces" / "p1" / "text.md").write_text(
        "# Titel\n\nRund 20 % bewegten sich stark [@W-0001, S. 3]. Laut @W-0001 sind es **viele**; siehe {{result:x.n}}.\n", encoding="utf-8")
    assert pieces.check("p1", p)[0] == []
    m = render.render("p1", "text", project=p)
    assert (m["kind"], m["design"], m["files"], m["results"], m["sources"]) == ("text", "sourcebound", ["p1.txt"], {"x.n": "7"}, ["W-0001"])
    assert (desk / "pieces" / "p1" / "render" / "text" / "p1.txt").read_text(encoding="utf-8") == (
        "Titel\n\nRund 20 % bewegten sich stark [1]. Laut Example Institute [1] sind es viele; siehe 7.\n\nQuellen:\n1. Example Institute (2024). Report on returns.\n")
    main(["render", "pieces/p1", "--template", "markdown"])
    md = (desk / "pieces" / "p1" / "render" / "markdown" / "p1.md").read_text(encoding="utf-8")
    assert "bewegten sich stark (Example Institute 2024, S. 3). Laut Example Institute (2024) sind" in md and "## Quellen\n\n- Example Institute (2024). Report on returns." in md
    # a number recorded anew makes the render stale, and the check says which
    results.save({"x.n": {"value": 8, "display": "8", "unit": None, "provenance": {"script": "analysis/a.py"}}}, p)
    assert any("render text shows older values of x.n" in w for w in pieces.check("p1", p)[1])
    assert [r["stale"] for r in pieces.summary(p)[0]["renders"]] == [["x.n"], ["x.n"]]
    with pytest.raises(RuntimeError, match="no installed plugin renders it"):
        (config.hub().registry / "templates" / "deck").mkdir(parents=True)
        (config.hub().registry / "templates" / "deck" / "template.yaml").write_text("kind: hologram\n", encoding="utf-8")
        render.render("p1", "deck", project=p)


def test_piece_decisions_belong_to_the_person(desk, capsys):
    from datetime import datetime, timedelta

    from sourcebound import config, pieces
    from sourcebound.cli import main
    p = config.project()
    a = pieces.add(p, title="Erste Notiz", kind="note")
    assert a["id"].endswith("-erste-notiz") and a["status"] == "idea" and a["lang"] == "de"
    with pytest.raises(ValueError, match="set later, by the person"):
        pieces.add(p, title="Zweite", status="published")
    with pytest.raises(SystemExit, match="this is the user's decision"):     # not a terminal: an agent cannot approve
        main(["piece", "set", a["id"], "--status", "approved"])
    with pytest.raises(SystemExit, match="this is the user's decision"):
        main(["piece", "set", a["id"], "--at", "2026-11-20 08:30"])
    main(["piece", "set", a["id"], "--status", "review", "--channel", "linkedin"])
    with pytest.raises(ValueError, match="needs a date and time"):
        pieces.update(a["id"], p, status="scheduled")
    past = (datetime.now() - timedelta(hours=1)).isoformat(timespec="minutes")
    before, after = pieces.update(a["id"], p, status="scheduled", scheduled_at=past, text="Neu.")
    assert (before["status"], before["text"], after["status"], after["text"]) == ("review", "", "scheduled", "Neu.")
    assert [x["id"] for x in pieces.due(p)] == [a["id"]]
    assert pieces.update(a["id"], p, scheduled_at="")[1]["status"] == "approved"         # unscheduling keeps the approval
    removed = pieces.remove(a["id"], p)
    assert removed["text"] == "Neu." and pieces.load(p) == [] and pieces.restore(a["id"], p)["title"] == "Erste Notiz"


def test_designs_templates_and_packs(hub, tmp_path):
    from sourcebound import assets, config
    assert assets.design()["colors"]["primary"] == "#1f3a5f" and assets.design()["charts"]["min_gap_px"] == 8
    assert {"markdown": "markdown", "text": "text"}.items() <= {t["id"]: t["kind"] for t in assets.templates()}.items()   # plus what plugins bring
    assert assets.design()["fonts"]["weights"]["medium"] == 600 and assets.design()["colors"]["accent_soft"]
    d = assets.new_design("acme", "Acme Research")
    doc = yaml.safe_load((d / "design.yaml").read_text(encoding="utf-8"))
    doc["colors"]["primary"] = "#223344"
    (d / "design.yaml").write_text(yaml.safe_dump({"name": doc["name"], "colors": {"primary": "#223344"}}), encoding="utf-8")
    got = assets.design("acme")
    assert (got["name"], got["colors"]["primary"], got["colors"]["accent"], got["folder"]) == ("Acme Research", "#223344", "#0b84c6", str(d))
    with pytest.raises(FileNotFoundError):
        assets.design("nobody")
    src = tmp_path / "post"
    src.mkdir()
    (src / "template.yaml").write_text("kind: text\ntitle: Post text\ndesign: acme\nfor: [piece]\n", encoding="utf-8")
    (src / "note.txt").write_text("x", encoding="utf-8")
    assert assets.add_template(src, "acme-post").name == "acme-post" and assets.template("acme-post")["design"] == "acme"
    with pytest.raises(ValueError, match="no plugin offers a starting template of kind hologram"):
        assets.new_template("acme-report", "hologram")       # a kind no plugin has, whichever are installed
    # a pack carries an organisation's design and templates to another machine
    pack = assets.export_pack(tmp_path / "pack", designs_=["acme"], templates_=["acme-post"])
    import shutil
    shutil.rmtree(config.hub().registry / "designs")
    shutil.rmtree(config.hub().registry / "templates")
    done = assets.install_pack(pack)
    assert (done["designs"], done["templates"], done["replaced"]) == (["acme"], ["acme-post"], [])
    assert done["pack"]["source"] == str(pack) and len(done["pack"]["sha256"]) == 64      # where it came from is recorded
    assert assets.design("acme")["colors"]["primary"] == "#223344" and (config.hub().registry / "templates" / "acme-post" / "note.txt").exists()
    with pytest.raises(FileNotFoundError, match="holds neither"):
        assets.install_pack(tmp_path)


def test_sql_is_read_only(hub):
    from sourcebound import connections, lake
    lake.write(_prices(), "market.prices", note="prices")
    lake._CON.close()
    lake._CON = None
    out = connections.sql("lake", "SELECT id, count(*) AS n FROM market.prices GROUP BY 1", limit=10)
    assert (out["columns"], out["rows"], out["truncated"]) == (["id", "n"], [["a", 3]], False)
    assert connections.sql("lake", "SELECT * FROM market.prices ORDER BY date", limit=2)["truncated"]
    assert connections.read_only("WITH t AS (SELECT 'drop table x; -- not code' AS s) SELECT * FROM t;").startswith("WITH")
    for bad, why in (("DROP TABLE market.prices", "not DROP"), ("SELECT 1; DELETE FROM market.prices", "one statement only"),
                     ("WITH x AS (SELECT 1) INSERT INTO market.prices SELECT * FROM x", "`INSERT` is not allowed"),
                     ("COPY market.prices TO 'x.csv'", "not COPY"), ("", "no statement")):
        with pytest.raises(ValueError, match=why):
            connections.sql("lake", bad)
    with pytest.raises(ValueError, match="not a database source"):
        connections.sql("ecb", "SELECT 1")
    assert [t["id"] for t in connections.targets()] == ["lake"]


def test_mcp_register_and_project_link(desk, monkeypatch):
    from sourcebound import connections
    from sourcebound.cli import main
    main(["mcp", "add", "warehouse", "--command", "npx -y @acme/warehouse-mcp --read-only", "--env", "WAREHOUSE_TOKEN"])
    main(["mcp", "add", "docs", "--url", "https://mcp.example.org/mcp"])
    with pytest.raises(SystemExit, match="NAME of a variable, never its value"):
        main(["mcp", "add", "leaky", "--url", "https://x.example", "--env", "TOKEN=abc"])
    monkeypatch.setenv("WAREHOUSE_TOKEN", "secret-value")
    rows = {s["name"]: s for s in connections.mcp_list()}
    assert rows["warehouse"]["env"] == [{"name": "WAREHOUSE_TOKEN", "set": True}] and rows["docs"]["transport"] == "http"
    (desk / ".mcp.json").write_text(json.dumps({"mcpServers": {"own": {"command": "x"}}}), encoding="utf-8")
    main(["mcp", "link"])
    doc = json.loads((desk / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert doc["own"] == {"command": "x"} and doc["docs"] == {"type": "http", "url": "https://mcp.example.org/mcp"}
    assert doc["warehouse"] == {"command": "npx", "args": ["-y", "@acme/warehouse-mcp", "--read-only"], "env": {"WAREHOUSE_TOKEN": "${WAREHOUSE_TOKEN}"}}
    assert "secret-value" not in (desk / ".mcp.json").read_text(encoding="utf-8")


def test_jobs_run_when_due_and_record_failures(hub, tmp_path, capsys):
    from sourcebound import config, jobs
    from sourcebound.cli import main
    ok, bad = tmp_path / "ok.py", tmp_path / "bad.py"
    ok.write_text("print('42 rows')\n", encoding="utf-8")
    bad.write_text("import sys\nsys.exit('Blocked: host stopped')\n", encoding="utf-8")
    main(["job", "add", "fine", "--run", str(ok), "--every", "1d", "--table", "market.prices"])
    main(["job", "add", "broken", "--run", str(bad), "--every", "30m"])
    with pytest.raises(SystemExit, match="a number and m, h, d or w"):
        main(["job", "add", "odd", "--run", str(ok), "--every", "sometimes"])
    assert [(j["id"], j["due"], j["last_run"]) for j in jobs.listing()] == [("broken", True, None), ("fine", True, None)]
    lines = jobs.run_due()
    assert [(x["job"], x["status"], x["blocked"]) for x in lines] == [("broken", "failed", True), ("fine", "ok", False)]
    state = {j["id"]: j for j in jobs.listing()}
    assert not state["fine"]["due"] and state["fine"]["last_status"] == "ok" and "Blocked" in state["broken"]["last_message"]
    assert jobs.run_due() == [] and len(jobs.log()) == 2            # nothing is due again; a failed job waits its interval too
    f = config.hub().registry / "jobs" / "fine.yaml"
    f.write_text(f.read_text(encoding="utf-8").replace("enabled: true", "enabled: false"))
    assert not {j["id"]: j for j in jobs.listing()}["fine"]["enabled"]
    main(["job", "schedule"])
    assert "job run --due" in capsys.readouterr().out


def test_system_report_and_new_endpoints(desk):
    from sourcebound import pieces, system, ui
    rep = system.report(sizes=False)
    assert rep["sourcebound"]["version"] and rep["lake"]["tables"] == 0 and rep["registry"]["templates"] >= 2
    assert {r["kind"] for r in rep["renderers"]} >= {"markdown", "text"} and {s["id"] for s in rep["setup"]} >= {"path", "hooks", "frontend"}
    json.dumps(rep)                                             # the report is plain data
    out = ui.piece("topic", {"op": "add", "title": "Über die API", "text": "Text [@W-0001]."})
    pid = out["piece"]["id"]
    assert ui.piece("topic", {"op": "check", "id": pid})["errors"] == ["source W-0001 is cited but not in evidence/sources.yaml (sb snap URL, or sb doc FILE)"]
    r = ui.piece("topic", {"op": "render", "id": pid, "template": "text"})["render"]
    listed = ui.pieces_of("topic")
    assert listed["preview"] == {}                              # who posts: from project.yaml, else the person's setting
    card = ui.project_roots()["topic"] / "project.yaml"
    card.write_text(card.read_text(encoding="utf-8") + 'preview: {author: "Example GmbH", headline: ""}\n', encoding="utf-8")
    assert ui.pieces_of("topic")["preview"] == {"author": "Example GmbH"}
    assert listed["pieces"][0]["renders"][0]["files"] == [f"pieces/{pid}/render/text/{pid}.txt"] and r["files"] == [f"{pid}.txt"]
    assert ui.text_file("topic", f"pieces/{pid}/render/text/{pid}.txt")["text"].startswith("Text [1].")
    assert ui.piece("topic", {"op": "rm", "id": pid})["removed"]["title"] == "Über die API" and pieces.load() == []
    assert ui.piece("topic", {"op": "restore", "id": pid})["piece"]["id"] == pid
    assert ui.lake_overview()["tables"] == [] and "sourcebound" in [d["id"] for d in ui.assets_overview()["designs"]]
    assert ui.connections_overview()["sql_targets"][0]["id"] == "lake" and ui.jobs_overview()["jobs"] == []


def test_checkout_follows_the_machines_data_root_and_projects_folder(tmp_path, monkeypatch):
    """`sb init --data-root A --projects-dir B`, then work from the checkout: both apply there too."""
    from sourcebound import config
    from sourcebound.cli import main
    data, research, checkout = tmp_path / "data core", tmp_path / "research", tmp_path / "checkout"
    main(["init", "--data-root", str(data), "--projects-dir", str(research)])
    checkout.mkdir()
    (checkout / "hub.toml").write_text("[fetch]\nmin_interval = 0.0\n[templates]\nproject = '%s'\n" % (ROOT / "templates" / "project"), encoding="utf-8")
    monkeypatch.chdir(checkout)
    config._load_hub.cache_clear()
    h = config.hub()
    assert (h.source, h.lake_root, h.projects_dir, h.registry) == ("hub", data.resolve(), research.resolve(), data.resolve() / "registry")
    assert (data / "registry" / "contracts").is_dir() and (data / "raw").is_dir()
    main(["new", "first", "--title", "First", "--kind", "desk"])
    main(["new", "second", "--title", "Second", "--empty"])
    assert (research / "first" / "project.yaml").exists() and (research / "second" / "hypotheses.yaml").exists()
    assert not (checkout / "first").exists()
    monkeypatch.chdir(research / "second")                       # and from a project the same data root
    assert config.hub().lake_root == data.resolve()
    # a hub.toml that names a data root keeps it
    (checkout / "hub.toml").write_text("[lake]\nroot = '%s'\n" % (tmp_path / "own"), encoding="utf-8")
    monkeypatch.chdir(checkout)
    config._load_hub.cache_clear()
    assert config.hub().lake_root == tmp_path / "own"


def test_other_formats_show_table_cells_as_printed(hub, monkeypatch):
    from sourcebound import render, tables
    from sourcebound.cli import main
    main(["new", "study", "--title", "A Study"])
    monkeypatch.chdir(hub / "study")
    tables.from_rows(hub / "study" / "tables" / "stats.tex", header=["Series", "Mean (%)", "Days"],
                     rows=[["EUR/USD", -0.0009529106, 7136], ["USD_index", 1234.5678, 12]], decimals=[0, 4, 0])
    assert (hub / "study" / "tables" / "stats.csv").read_text(encoding="utf-8").splitlines()[1] == "EUR/USD,-0.0009529106,7136"   # exact
    assert tables.displayed(hub / "study" / "tables" / "stats.tex") == (
        ["Series", "Mean (\\%)", "Days"], [["EUR/USD", "\u22120.0010", "7,136"], ["USD\\_index", "1,234.5678", "12"]])
    tables.from_rows(hub / "study" / "tables" / "wide.tex", header=["", "Mean"], rows=[["EUR/USD", 0.5]])
    assert tables.displayed(hub / "study" / "tables" / "wide.tex") == (["", "Mean"], [["EUR/USD", "0.50"]])     # an empty corner cell stays
    main(["handover"])
    shown = render._tables(hub / "study" / "dist" / "handover" / "tables")["stats"]
    assert shown == {"columns": ["Series", "Mean (%)", "Days"], "rows": [["EUR/USD", "\u22120.0010", "7,136"], ["USD_index", "1,234.5678", "12"]]}


def test_init_asks_a_person_and_refuses_to_guess_for_an_agent(tmp_path, monkeypatch, capsys):
    from sourcebound import config
    from sourcebound.cli import main
    with pytest.raises(SystemExit, match="name the two folders"):          # no terminal, no folders: not a default to guess
        main(["init"])
    assert not config.user_config_path().exists()
    answers = iter([str(tmp_path / "lake"), "", "acme", ""])               # Enter takes the suggestion (no desktop icon)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    from sourcebound import shortcut
    monkeypatch.setattr(shortcut, "create", lambda folder=None: pytest.fail("no icon was asked for"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True, raising=False)
    for var in ("HOME", "USERPROFILE"):                                    # the home folder, on every system
        monkeypatch.setenv(var, str(tmp_path / "home"))
    main(["init"])
    assert "data root:" in capsys.readouterr().out
    cfg = config.user_config_path().read_text(encoding="utf-8")
    assert (tmp_path / "lake").resolve().as_posix() in cfg                # paths are written with forward slashes
    assert 'owner = "acme"' in cfg and "Documents/research" in cfg
    assert (tmp_path / "lake" / "registry" / "contracts").is_dir() and (tmp_path / "home" / "Documents" / "research").is_dir()
    main(["init"])                                                         # a second run keeps the file
    assert "keeping" in capsys.readouterr().out


def test_init_defaults_without_asking(tmp_path, monkeypatch):
    from sourcebound import config
    from sourcebound.cli import main
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(tmp_path))
    main(["init", "--defaults"])
    config._load_hub.cache_clear()
    monkeypatch.chdir(tmp_path)
    h = config.hub()
    assert (h.lake_root, h.projects_dir) == ((tmp_path / "research-lake").resolve(), (tmp_path / "Documents" / "research").resolve())


def test_a_plugin_can_bring_a_pack(hub, tmp_path):
    """An organisation's design as an installable package: found without `sb pack install`; the registry still wins."""
    from sourcebound import assets, config, plugins
    pack = tmp_path / "pkg" / "pack"
    (pack / "designs" / "firm").mkdir(parents=True)
    (pack / "designs" / "firm" / "design.yaml").write_text("name: Firm\ncolors: {primary: '#223344'}\n", encoding="utf-8")
    (pack / "templates" / "firm-post").mkdir(parents=True)
    (pack / "templates" / "firm-post" / "template.yaml").write_text("kind: text\ntitle: Firm post\ndesign: firm\n", encoding="utf-8")
    reg = plugins.load(fresh=True)
    p = plugins.Plugin("firm")
    plugins.Api(p, reg).pack(pack)
    reg.plugins.append(p)
    try:
        assert assets.design("firm")["colors"]["primary"] == "#223344"
        assert {"id": "firm-post", "origin": "plugin", "design": "firm"}.items() <= next(t for t in assets.templates() if t["id"] == "firm-post").items()
        assert next(x for x in plugins.listing() if x["name"] == "firm")["packs"] == [str(pack)]
        own = config.hub().registry / "designs" / "firm"
        own.mkdir(parents=True)
        (own / "design.yaml").write_text("name: Firm (this machine)\ncolors: {primary: '#445566'}\n", encoding="utf-8")
        assert assets.design("firm")["name"] == "Firm (this machine)"
    finally:
        plugins.load(fresh=True)


# ----------------------------------------------------------------------------- reading registered sources
def _tiny_docx(path):
    """A Word file with a field code, a text box (choice + fallback), a table, a footnote, an endnote and an image."""
    import zipfile
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = (
        f'<?xml version="1.0"?><w:document {w}><w:body>'
        '<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
        '<w:r><w:t>Abb. </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> SEQ Abbildung \\* ARABIC </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
        '<w:r><w:t xml:space="preserve">: Assets &amp; savings</w:t></w:r>'
        '<w:r><w:footnoteReference w:id="7"/></w:r></w:p>'
        '<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:anchor>'
        '<wp:positionH relativeFrom="column"><wp:posOffset>-1168404937125</wp:posOffset></wp:positionH>'
        '<wps:txbx><w:txbxContent><w:p><w:r><w:t>Box text</w:t></w:r></w:p></w:txbxContent></wps:txbx>'
        '</wp:anchor></w:drawing></mc:Choice><mc:Fallback><w:pict><v:textbox><w:txbxContent><w:p><w:r><w:t>Box text</w:t></w:r></w:p>'
        '</w:txbxContent></v:textbox></w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>'
        '<w:tbl><w:tblPr/><w:tr><w:tc><w:tcPr/><w:p><w:r><w:t>Year</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Share</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>2024</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>20 %</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        '<w:p><w:r><w:t>See also</w:t></w:r><w:r><w:endnoteReference w:id="2"/></w:r><w:r><w:delText>gone</w:delText></w:r></w:p>'
        '</w:body></w:document>')
    notes = (f'<w:footnotes {w}><w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
             '<w:footnote w:id="7"><w:p><w:r><w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> Source: Example statistics office, 2024.</w:t></w:r></w:p></w:footnote>'
             '</w:footnotes>')
    ends = f'<w:endnotes {w}><w:endnote w:id="2"><w:p><w:r><w:endnoteRef/></w:r><w:r><w:t>An endnote.</w:t></w:r></w:p></w:endnote></w:endnotes>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", body)
        z.writestr("word/footnotes.xml", notes)
        z.writestr("word/endnotes.xml", ends)
        z.writestr("word/media/image1.png", b"\x89PNG not really")
    return path


def test_word_text_drops_noise_and_keeps_notes_and_tables(tmp_path):
    from sourcebound.cli_more import document_info, document_text
    f = _tiny_docx(tmp_path / "r.docx")
    text = document_text(f.read_bytes(), f.name)
    assert "Abb. 1: Assets & savings[^1]" in text
    for noise in ("SEQ", "ARABIC", "1168404937125", "gone"):
        assert noise not in text
    assert text.count("Box text") == 1
    assert "Year | Share\n2024 | 20 %\n" in text
    assert "See also[^E1]" in text
    assert text.index("Footnotes\n[^1] Source: Example statistics office, 2024.") < text.index("Endnotes\n[^E1] An endnote.")
    assert document_info(f.read_bytes(), f.name) == {"images": 1, "charts": 0}


def test_slides_in_presentation_order(tmp_path):
    import zipfile

    from sourcebound.cli_more import document_text
    f = tmp_path / "d.pptx"
    slide = lambda t: f'<p:sld><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:sld>'
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("ppt/slides/slide2.xml", slide("second file"))
        z.writestr("ppt/slides/slide10.xml", slide("tenth file"))
        z.writestr("ppt/presentation.xml", '<p:presentation><p:sldIdLst><p:sldId id="256" r:id="rId3"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst></p:presentation>')
        z.writestr("ppt/_rels/presentation.xml.rels", '<Relationships><Relationship Id="rId2" Type="x/slide" Target="slides/slide2.xml"/>'
                   '<Relationship Id="rId3" Type="x/slide" Target="slides/slide10.xml"/></Relationships>')
    assert document_text(f.read_bytes(), f.name) == "[slide 1]\ntenth file\n\n[slide 2]\nsecond file\n"


def test_reading_a_long_source_says_what_is_cut_and_greps_merged(desk, tmp_path, capsys):
    import re

    from sourcebound.cli import main
    report = tmp_path / "long.txt"
    report.write_text(("word " * 1000) + "needle and needle again " + ("filler " * 200) + "needle at the end\n", encoding="utf-8")
    main(["doc", str(report), "--title", "Long report"])
    capsys.readouterr()
    main(["source", "W-0001"])
    out = capsys.readouterr().out
    assert "W-0001  Long report\n" in out
    assert re.search(r"word\n\n\.\.\. \(3,99\d of 6,\d{3} characters shown; --chars N for more, --chars 0 for all", out)   # ends on a word
    main(["source", "W-0001", "--chars", "0"])
    assert "needle at the end" in capsys.readouterr().out
    main(["source", "W-0001", "--grep", "needle"])
    out = capsys.readouterr().out
    assert out.count('3 hits for "needle" in 2 passages') == 1
    assert "[1] hits 1-2: ... " in out and "[2] hit 3: ... " in out and out.count("needle and needle again") == 1
    dest = tmp_path / "all.txt"
    main(["source", "W-0001", "--out", str(dest)])
    assert "wrote" in capsys.readouterr().out and dest.read_text(encoding="utf-8") == report.read_text(encoding="utf-8")


def test_the_same_document_keeps_its_id_and_its_name_can_be_corrected(desk, tmp_path, capsys):
    from sourcebound import ledger
    from sourcebound.cli import main
    f = _tiny_docx(tmp_path / "Report 2024.docx")
    main(["doc", str(f), "--title", "Annual report", "--publisher", "Example Institute"])
    assert "W-0001  Annual report (Example Institute)\n      file Report 2024.docx" in capsys.readouterr().out
    head = (desk / "evidence" / "sources.yaml").read_text(encoding="utf-8").splitlines()[0]
    main(["doc", str(f), "--title", "Same bytes"])
    assert "already registered as W-0001  Annual report (Example Institute)" in capsys.readouterr().out
    assert [s["id"] for s in ledger.load()["sources"]] == ["W-0001"]
    main(["doc", str(f), "--title", "On purpose", "--new"])
    assert [s["id"] for s in ledger.load()["sources"]] == ["W-0001", "W-0002"]
    main(["source", "set", "W-0001", "--publisher", "Example Institute e.V."])
    assert "publisher: Example Institute -> Example Institute e.V." in capsys.readouterr().out
    s = ledger.load()["sources"][0]
    assert (s["title"], s["publisher"], s["file"]) == ("Annual report", "Example Institute e.V.", "Report 2024.docx")
    assert (desk / "evidence" / "sources.yaml").read_text(encoding="utf-8").splitlines()[0] == head   # comment kept
    main(["source", "W-0001"])
    out = capsys.readouterr().out
    assert out.startswith("W-0001  Annual report (Example Institute e.V.)\n      file Report 2024.docx")
    assert "1 image not read (charts and figures are not text)" in out and "Footnotes\n[^1] Source:" in out
    for bad in (["source", "set", "W-0009", "--title", "x"], ["source", "set", "W-0001"], ["source", "W-0001", "--title", "x"]):
        with pytest.raises(SystemExit):
            main(bad)


def test_new_maps_hyphens_and_a_desk_ignores_heavy_renders(hub, capsys):
    import subprocess

    from sourcebound.cli import main
    main(["new", "my-desk", "--title", "Hyphens", "--kind", "desk"])
    assert "slug my_desk (hyphens become underscores)" in capsys.readouterr().out
    d = hub / "my_desk"
    assert yaml.safe_load((d / "project.yaml").read_text(encoding="utf-8"))["slug"] == "my_desk"
    r = d / "pieces" / "p1" / "render" / "deck"
    (r / "post").mkdir(parents=True)
    for name in ("deck_slide_1.png", "deck.pdf", "deck.html", "post/deck_slide_1.png", "render.json", "preview.json", "layout.json"):
        (r / name).write_text("x", encoding="utf-8")
    ignored = lambda f: subprocess.run(["git", "check-ignore", "-q", f"pieces/p1/render/deck/{f}"], cwd=d).returncode == 0
    assert [ignored(f) for f in ("deck_slide_1.png", "deck.pdf", "deck.html", "post/deck_slide_1.png")] == [True] * 4
    assert [ignored(f) for f in ("render.json", "preview.json", "layout.json")] == [False] * 3


# The texts of three test posts (company names replaced), for the number rule of pieces.
_POST_AVD = """Ab 2027 legt der Staat im neuen Altersvorsorgedepot auf die ersten 360 € Eigenbeitrag 50 % drauf [@W-0001].

Das Altersvorsorgedepot ersetzt die Riester-Rente. Bundestag und Bundesrat haben die Reform im Mai 2026 beschlossen; neue Riester-Verträge gibt es ab 2027 nicht mehr, bestehende laufen weiter [@W-0001].

Die Regeln, wie sie unsere Marktübersicht zusammenfasst:

- Gefördert werden Eigenbeiträge von 120 € bis 1.800 € im Jahr [@W-0001].
- Die Grundzulage beträgt 50 % auf die ersten 360 € und 25 % auf den Teil bis 1.800 €, zusammen höchstens 540 € im Jahr [@W-0001].
- Je Kind kommt 1 € Zulage je eingezahltem Euro dazu, höchstens 300 € im Jahr [@W-0001].
- Jeder Anbieter muss ein Standarddepot anbieten oder auf das eines Partners verweisen; dessen Effektivkosten sind auf 1,0 % begrenzt [@W-0001].

Was das heißt, in eigener Rechnung: Bei 1.000 € Eigenbeitrag im Jahr beträgt die Grundzulage {{result:avd.zulage_1000}} €, eine Förderquote von {{result:avd.quote_1000}}. Beim Höchstbeitrag sind es {{result:avd.zulage_1800}} € oder {{result:avd.quote_1800}}. Mit einem Kind steigt die Quote beim Höchstbeitrag auf {{result:avd.quote_1800_kind}}.

Anders als bei Riester gibt es Varianten ohne Beitragsgarantie [@W-0001]. Das öffnet nach unserer Einschätzung einen neuen Massenmarkt für günstige Fonds- und ETF-Portfolios [@W-0001].

#Altersvorsorge #ETF #Fonds
"""
_POST_SELF = """Von 37,2 Mio. Wertpapierdepots in Deutschland lagen Ende 2025 16,2 Mio. bei Online-, Direkt- und Neobrokern [@W-0001]. Das sind {{result:se.anteil_online}} (eigene Rechnung).

Dazu passt eine zweite Zahl: Rund 5,8 Mio. ETF-Sparpläne werden pro Monat ausgeführt [@W-0001].

Wie schnell einzelne Anbieter wachsen, zeigt ein Neobroker. Nach Unternehmensangaben hatte der Broker 2021 rund 1 Mio. Kunden und 6 Mrd. € Kundengelder, im September 2025 europaweit rund 10 Mio. Kunden und 150 Mrd. € [@W-0001]. Das ist das {{result:se.tr_faktor_kunden}}-Fache bei den Kunden und das {{result:se.tr_faktor_gelder}}-Fache bei den Kundengeldern (eigene Rechnung). Die Zahlen gelten für ganz Europa und lassen sich nicht mit dem deutschen Markt gleichsetzen [@W-0001].

Für Produktanbieter heißt das: Ein wachsender Teil der Anleger entscheidet selbst, per App und Sparplan. Wer nur über Berater und Filialen vertreibt, erreicht diesen Teil nicht. Das ist unsere Einordnung.

#ETF #Neobroker #Sparplan
"""
_POST_AGENTS = """Auf einen Honorar-Finanzanlagenberater kommen in Deutschland rund {{result:verm.34f_je_34h}} Finanzanlagenvermittler (eigene Rechnung nach [@W-0001]).

Die Zahlen hinter dem Verhältnis:

- 41.499 Selbstständige haben eine eigene Erlaubnis nach § 34f GewO (Register, Stand 01.10.2026) [@W-0001]. Sie dürfen nur Fonds und Vermögensanlagen vermitteln, keine Einzelaktien, und werden von IHK oder Gewerbeamt beaufsichtigt, nicht von der BaFin [@W-0001].
- 396 Honorar-Finanzanlagenberater arbeiten nach § 34h GewO [@W-0001]. Sie werden, bis auf enge Ausnahmen, von ihren Kunden bezahlt statt von Produktanbietern [@W-0002].
- 16.211 Selbstständige ohne eigene Erlaubnis arbeiten als gebundene Vermittler unter 139 Haftungsdächern [@W-0001]. Das haftende Institut trägt die Verantwortung für sie [@W-0002].

Ein Haftungsdach betreut damit im Schnitt rund {{result:verm.gebunden_je_dach}} gebundene Vermittler (eigene Rechnung).

#Finanzvertrieb #Fonds #Vermittler
"""


def test_numbers_in_a_piece_with_units_and_citations():
    from sourcebound.pieces import typed_numbers
    got = lambda t: [(h["line"], h["number"], h["cited"]) for h in typed_numbers(t)]
    avd = got(_POST_AVD)
    assert [x for x in avd if not x[2]] == [(12, "1.000 €", False)]          # the input of the own calculation
    assert {n for n, _, _ in avd} == {1, 7, 8, 9, 10, 12}
    assert (9, "1 €", True) in avd and (10, "1,0 %", True) in avd and not any("2027" in x[1] or "2026" in x[1] for x in avd)
    self_ = got(_POST_SELF)
    assert {x[1] for x in self_} == {"37,2 Mio.", "16,2 Mio.", "5,8 Mio.", "1 Mio.", "6 Mrd.", "10 Mio.", "150 Mrd."}
    assert all(c for _, _, c in self_)                                    # "Mio. Kunden" does not end the sentence
    agents = got(_POST_AGENTS)
    assert agents == [(5, "41.499", True), (6, "396", True), (7, "16.211", True), (7, "139", True)]
    quiet = ("Am 01.10.2026 um 08:30 Uhr, seit 09.2025, am 2026-11-17, im 3. Quartal 2025, nach § 34f und Art. 6, "
             "siehe [@W-0001, S. 120]; 95 % Konfidenz; #ETF2027; W-0001; Datei cover_1080.png; 12 Monate; Stand 01.10.2026, neu.")
    assert got(quiet) == []
    assert got("Es sind 44 % der Depots. Das steht in [@W-0001].\nRund 1 Mio. Kunden kamen dazu [@W-0001].") == [
        (1, "44 %", False), (2, "1 Mio.", True)]


def test_piece_check_reads_slides_and_names_the_sources_of_results(desk, tmp_path, capfd):
    from sourcebound import config, pieces, results
    from sourcebound.cli import main
    report = tmp_path / "report.txt"
    report.write_text("Ein Report mit 540 € und 41.499 Personen.\n", encoding="utf-8")
    main(["doc", str(report), "--title", "Report on agents"])
    (desk / "analysis" / "a.py").write_text(
        "from sourcebound import results\n"
        "results.record('x.n', 7, sources=['W-0001'])\n"
        "results.record('x.m', 3, sources='W-0009')\n", encoding="utf-8")
    (desk / "analysis" / "b.py").write_text(
        "from sourcebound import results\nfor i in range(22):\n    results.record(f'k.{i:02d}', i, fmt='pct0')\n", encoding="utf-8")
    capfd.readouterr()
    main(["run", "analysis"])
    run = capfd.readouterr()
    assert "== analysis/a.py\n   x.m = 3\n   x.n = 7\n== analysis/b.py\n   k.00 = 0 %\n" in run.out
    assert "   k.19 = 1.900 %\n   … 2 more" in run.out and "k.20" not in run.out
    assert "result x.m: source W-0009 is not registered" in run.err
    p = config.project()
    assert results.load(p)["x.n"]["provenance"]["sources"] == ["W-0001"]
    warns = results.problems(p)[1]
    assert not any("no lake table" in w and "x.n" in w for w in warns)
    assert any("result x.m rests on source W-0009, which is not registered" in w for w in warns)
    pieces.add(p, piece_id="p1", title="Vermittler", text="Rund {{result:x.n}} Vermittler je Dach [@W-0001]. Es gibt 396 Berater.\n")
    (desk / "pieces" / "p1" / "slides.yaml").write_text(yaml.safe_dump({"slides": [
        {"title": "Vier Zahlen", "blocks": [{"type": "kpis", "items": [{"n": "540 €", "t": "höchste Zulage"}]}]},
        {"title": "Mit Quelle", "blocks": [{"type": "bars", "rows": [{"label": "§ 34f", "text": "41.499"}]}], "source": "[@W-0001]"},
    ]}, allow_unicode=True), encoding="utf-8")
    f = pieces.findings("p1", p)
    assert f["errors"] == []
    assert "text.md: numbers typed by hand with no citation in the same sentence, lines 1 (396)" in "\n".join(f["warnings"])
    assert "slides.yaml: numbers typed by hand with no citation (positions count from 1): slides[1].blocks[1].items[1].n “540 €”" in "\n".join(f["warnings"])
    assert any("slides.yaml: numbers quoted under a citation: slides[2].blocks[1].rows[1].text “41.499”" in i for i in f["info"])
    assert "result x.n rests on W-0001 (Report on agents)" in f["info"]
    with pytest.raises(SystemExit):                  # warnings only: exit 0
        main(["piece", "check", "p1"])
    assert "info:    p1: result x.n rests on W-0001" in capfd.readouterr().out


def test_desk_status_piece_ids_and_the_one_channel(desk, capsys):
    from sourcebound import config, pieces
    from sourcebound.cli import main
    card = desk / "project.yaml"
    card.write_text(card.read_text(encoding="utf-8").replace("channels: []", "channels: [linkedin]")
                    .replace('topic: ""', 'topic: "Fonds und ETFs in Deutschland"'), encoding="utf-8")
    p = config.project()
    a = pieces.add(p, title="Altersvorsorgedepot: bis zu 50 % Zulage ab 2027")
    assert a["id"].split("-", 1)[1] == "altersvorsorgedepot-bis-zu" and a["channel"] == "linkedin"
    b = pieces.add(p, title="Donaudampfschifffahrtsgesellschaftskapitaen erzaehlt", channel="newsletter")
    assert len(b["id"].split("-", 1)[1]) == 28 and b["channel"] == "newsletter"
    pieces.update(b["id"], p, status="review")
    main(["status"])
    out = capsys.readouterr().out
    assert "topic:   Fonds und ETFs in Deutschland\nchannels: linkedin\nsources: 0 registered" in out
    assert "pieces:  2 (idea 1, review 1)" in out and "results: 0 recorded" in out
    assert "pre-registration" not in out and "claims:" not in out


def test_a_sources_date_is_read_from_the_file_or_its_title():
    from sourcebound import srcdate
    page = b'<html><head><meta property="article:published_time" content="2026-10-02T07:00:00+02:00"><meta name="date" content="2020-01-01"></head></html>'
    assert srcdate.find(page, title="A press release") == ("2026-10-02", "the page's own date")
    assert srcdate.find(b'<html><script type="application/ld+json">{"datePublished": "2025-12-05"}</script></html>') == ("2025-12-05", "the page's own date")
    assert srcdate.find(b"<html><time datetime='2026-01-01'>today</time></html>") is None          # any <time> is not a publication date
    assert srcdate.find(b"<html></html>", title="Monetary policy assessment of 24 September 2026") == ("2026-09-24", "the date in its title")
    assert srcdate.find(None, title="Pressemitteilung vom 2. Oktober 2026") == ("2026-10-02", "the date in its title")
    assert srcdate.find(None, title="Code (December 2024 version)") == ("2024-12", "the date in its title")
    assert srcdate.find(None, title="Trading calendar 2026") is None                               # a year alone names a subject
    # a file put online years after the document it holds: the title's year wins
    assert srcdate.find(b'<html><meta name="dcterms.created" content="2024-11-12"></html>', title="Column 2022-01") == ("2022-01", "the date in its title")
    assert [srcdate.normal(x) for x in ("02.10.2026", "October 2, 2026", "20261002", "2026", "soon", "2026-13-01")] == \
        ["2026-10-02", "2026-10-02", "2026-10-02", "2026", None, None]


def test_a_new_source_gets_the_date_its_file_declares(desk, tmp_path, capsys):
    from sourcebound import ledger
    from sourcebound.cli import main
    (tmp_path / "dated.html").write_text('<html><head><meta property="article:published_time" content="2026-10-02T07:00:00Z"></head><body>x</body></html>', encoding="utf-8")
    (tmp_path / "undated.html").write_text("<html><body>nothing here</body></html>", encoding="utf-8")
    main(["doc", str(tmp_path / "dated.html"), "--title", "A release"])
    main(["doc", str(tmp_path / "undated.html"), "--title", "A page"])
    by_title = {s["title"]: s for s in ledger.load()["sources"]}
    assert by_title["A release"]["date"] == "2026-10-02" and "date" not in by_title["A page"]
    capsys.readouterr()
    main(["source", "dates", "--write"])
    assert "0 of 1 sources without a date" in capsys.readouterr().out
    main(["source", "set", by_title["A page"]["id"], "--date", "2026-11-01"])
    main(["source", "dates"])
    assert "every source has a date" in capsys.readouterr().out
