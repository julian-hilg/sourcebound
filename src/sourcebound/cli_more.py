"""Commands beyond the study workflow: pieces, rendering, designs and templates, jobs, connections.

  sb new SLUG --title "..." --kind desk      ongoing research on a topic (pieces instead of a paper)
  sb doc FILE --title "..." [--publisher P]  register a local document as a source (W-xxxx), archived
                                             (the same bytes again: the id they have; --new forces a new one)
  sb piece list | add "TITLE" [--kind K] [--template ID] [--id ID] | show ID | check [ID]
  sb piece set ID [--title ..] [--status ..] [--template ..] [--at "2026-11-20 08:30"] ...
  sb piece rm ID | due                       remove (kept in pieces/.removed) | what is scheduled and due
  sb render TARGET --template ID [--design ID]   a piece or deliverables/<name> in a registered format
  sb design list | show [ID] | new ID --name "..."
  sb template list | add FOLDER [--id ID] | new ID --kind KIND [--design ID] [--title "..."]
  sb pack install FOLDER | export FOLDER --design ID ... --template ID ...
  sb plugin list                             installed plugins and the formats they render
  sb job list | add ID --run "pipelines/x/pipeline.py" --every 6h | run [ID | --due] | log | schedule
  sb sql lake|SOURCE "SELECT ..."            one read-only statement (a look, not a load)
  sb mcp list | add NAME --url URL | --command "..." [--env VAR] | rm NAME | link [NAME ...]
  sb doctor --json                           the system report as data
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DOC_TYPES = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/plain", ".html": "text/html", ".htm": "text/html",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
             ".csv": "text/csv", ".json": "application/json"}


def _fail(e: Exception):
    sys.exit(str(e).strip("'\""))


IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf", ".svg", ".webp"}


def _ooxml_text(xml: str, ns: str, notes: dict | None = None) -> str:
    """Text of one WordprocessingML (`ns` "w") or DrawingML (`ns` "a") part.

    Only text runs (`<w:t>`, `<a:t>`) count, so field codes (`w:instrText`), deleted text,
    drawing offsets and other attribute-like content stay out.  `mc:Fallback` (the old copy
    of a text box) is dropped first, so a text box appears once.  A table cell ends with
    " | ", so a row stays on one line.  Footnote and endnote references become `[^1]`,
    `[^E1]`, numbered in the order they appear (`notes` collects the numbers).
    """
    import html as htmlmod
    import re
    while True:                                         # innermost first, so nested fallbacks go too
        xml, n = re.subn(r"(?s)<mc:Fallback\b[^>]*>(?:(?!<mc:Fallback\b).)*?</mc:Fallback>", "", xml)
        if not n:
            break
    xml = re.sub(r"(?s)<w:tabs>.*?</w:tabs>", "", xml)  # tab stops of a paragraph, not tabs in the text
    tok = re.compile(
        rf"<{ns}:t(?:\s[^>]*)?>(?P<t>.*?)</{ns}:t>|<(?P<tc>/?){ns}:tc(?=[\s>])[^>]*?(?P<tcself>/?)>|</{ns}:tr>(?P<tr>)"
        rf"|</{ns}:p>(?P<p>)|<{ns}:(?P<br>br|cr|tab)\b[^>]*/>|<w:noBreakHyphen\s*/>(?P<hy>)"
        r'|<w:(?P<note>footnote|endnote)Reference\b[^>]*?w:id="(?P<nid>-?\d+)"[^>]*/>', re.S)
    out, depth = [], 0
    for m in tok.finditer(xml):
        if m.group("t") is not None:
            out.append(htmlmod.unescape(m.group("t")))
        elif m.group("tc") is not None:
            if m.group("tc"):                           # </w:tc>
                depth = max(0, depth - 1)
                out.append("\x00")
            elif not m.group("tcself"):
                depth += 1
            else:
                out.append("\x00")
        elif m.group("tr") is not None:
            out.append("\x02" if depth else "\x01")    # a row of a table inside a cell, or of a table
        elif m.group("p") is not None:
            out.append(" " if depth else "\n")
        elif m.group("br"):
            out.append("\t" if m.group("br") == "tab" else (" " if depth else "\n"))
        elif m.group("hy") is not None:
            out.append("-")
        elif m.group("note"):
            kind, nid = m.group("note"), m.group("nid")
            seen = (notes if notes is not None else {}).setdefault(kind, {})
            seen.setdefault(nid, len(seen) + 1)
            out.append(f"[^{'E' if kind == 'endnote' else ''}{seen[nid]}]")
    t = "".join(out)
    t = re.sub(r"(?:[ \t]*\x00)*[ \t]*\x02", " ; ", t)      # empty cells at a row's end say nothing
    t = re.sub(r"(?:[ \t]*\x00)*[ \t]*\x01", "\n", t)
    t = re.sub(r"[ \t]*\x00[ \t]*", " | ", t)
    t = re.sub(r"[ \t]{2,}", " ", re.sub(r"[ \t]+\n", "\n", t))
    return re.sub(r"\n{3,}", "\n\n", t)


def _word_notes(xml: str, kind: str, numbers: dict) -> list[str]:
    """Lines `[^1] text` of word/footnotes.xml or word/endnotes.xml, numbered as referenced in the body."""
    import re
    mark = "E" if kind == "endnote" else ""
    rows = []
    for m in re.finditer(rf"(?s)<w:{kind}\b([^>]*)>(.*?)</w:{kind}>", xml):
        if re.search(r'\bw:type="', m.group(1)):        # separator lines, not notes
            continue
        nid = (re.search(r'\bw:id="(-?\d+)"', m.group(1)) or [None, "?"])[1]
        text = re.sub(r"\s*\n\s*", " ", _ooxml_text(m.group(2), "w")).strip()
        if text:
            numbers.setdefault(nid, len(numbers) + 1)
            rows.append((numbers[nid], f"[^{mark}{numbers[nid]}] {text}"))
    return [r for _, r in sorted(rows)]


def _slide_order(z) -> list[str]:
    """Slide parts in presentation order (presentation.xml), else by number."""
    import re
    names = set(z.namelist())
    slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    try:
        rels = z.read("ppt/_rels/presentation.xml.rels").decode("utf-8", errors="replace")
        target = {m.group(1): "ppt/" + m.group(2).lstrip("/").removeprefix("ppt/") for m in
                  re.finditer(r'<Relationship\b[^>]*?Id="([^"]+)"[^>]*?Target="([^"]+)"', rels)}
        pres = z.read("ppt/presentation.xml").decode("utf-8", errors="replace")
        order = [target.get(r) for r in re.findall(r'<p:sldId\b[^>]*?r:id="([^"]+)"', pres)]
        order = [n for n in order if n in names]
        return order + [n for n in slides if n not in order] if order else slides
    except KeyError:
        return slides


def document_info(body: bytes, name: str) -> dict:
    """What a document holds that its text does not show: {"images": n, "charts": n}."""
    import io
    import re
    import zipfile
    if Path(name).suffix.lower() not in {".docx", ".pptx"}:
        return {"images": 0, "charts": 0}
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
    except zipfile.BadZipFile:
        return {"images": 0, "charts": 0}
    return {"images": sum(1 for n in names if re.match(r"(word|ppt)/media/", n) and Path(n).suffix.lower() in IMAGE_EXT),
            "charts": sum(1 for n in names if re.fullmatch(r"(word|ppt)/charts/chart\d+\.xml", n))}


def document_text(body: bytes, name: str) -> str:
    """Readable text of an archived document, by its file name (docx, pptx, html, text).

    Word: the body, then footnotes and endnotes under a heading line, numbered as in the body
    (`[^1]`).  PowerPoint: the slides in presentation order, each under `[slide N]`.
    """
    import html as htmlmod
    import io
    import re
    import zipfile
    suffix = Path(name).suffix.lower()
    if suffix == ".docx":
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            read = lambda n: z.read(n).decode("utf-8", errors="replace") if n in z.namelist() else ""
            numbers: dict = {}
            text = _ooxml_text(read("word/document.xml"), "w", numbers).strip("\n")
            for kind, part, heading in (("footnote", "word/footnotes.xml", "Footnotes"), ("endnote", "word/endnotes.xml", "Endnotes")):
                rows = _word_notes(read(part), kind, numbers.setdefault(kind, {}))
                if rows:
                    text += f"\n\n{heading}\n" + "\n".join(rows)
        return text + "\n"
    if suffix == ".pptx":
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            slides = [z.read(n).decode("utf-8", errors="replace") for n in _slide_order(z)]
        return "\n\n".join(f"[slide {i}]\n" + _ooxml_text(x, "a").strip("\n") for i, x in enumerate(slides, 1)) + "\n"
    t = body.decode("utf-8", errors="replace")
    if suffix in {".html", ".htm"}:
        t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", t)
        t = htmlmod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)))
    return t


def cmd_doc(a):
    """A local document (report, PDF, Word file) as a citable source: archived unchanged, id W-xxxx."""
    from datetime import datetime, timezone

    from . import ledger
    from .fetch import EXT, Fetcher
    f = Path(a.file).expanduser()
    if not f.is_file():
        sys.exit(f"{f}: no such file")
    ctype = DOC_TYPES.get(f.suffix.lower(), "application/octet-stream")
    EXT.setdefault(DOC_TYPES[".docx"], "docx")
    EXT.setdefault(DOC_TYPES[".pptx"], "pptx")
    ref = Fetcher("web").store(f.read_bytes(), url=f"file:{f.name}", content_type=ctype, meta={"file": f.name})
    entry = {"title": a.title or f.stem, "url": f"file:{f.name}", "publisher": a.publisher or "",
             "accessed": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sha256": ref.sha256,
             "raw": ref.path, "file": f.name, "kind": "document", "note": a.note or "",
             **({"author": a.author} if a.author else {})}
    from .cli import _published
    dated = _published(a.date, ref.sha256, f.name, a.title or "")
    if dated:
        entry["date"] = dated[0]
    sid, created = ledger.register_source(entry, new=a.new)
    if not created:
        from .cli import already_registered
        print(already_registered(sid, ref.sha256))
        return
    print(f"{sid}  {ledger.source_label(entry)}\n      file {f.name}, archived raw/{ref.path}  "
          f"(cite as [@{sid}]; read it with `sb source {sid}`)")


def cmd_piece(a):
    from . import config, pieces
    fields = {k: getattr(a, k) for k in ("title", "kind", "template", "design", "status", "lang", "channel", "note", "prompt", "url", "self_citation")
              if getattr(a, k, None) is not None}
    if a.at is not None:
        fields["scheduled_at"] = a.at
    try:
        if a.what == "list":
            rows = pieces.load()
            for x in rows:
                when = f"  at {x['scheduled_at']}" if x.get("scheduled_at") else ""
                print(f"{x['id']:<44} {x.get('status', ''):<10}{x.get('kind', ''):<9}{x.get('title', '')}{when}")
            print(f"{len(rows)} pieces")
        elif a.what == "add":
            if not a.args:
                sys.exit('usage: sb piece add "TITLE" [--kind post] [--template ID] [--id ID]')
            p = config.project()
            defaults = p.meta.get("piece_defaults") or {}
            for k in ("template", "design"):
                fields.setdefault(k, defaults.get(k) or "")
            x = pieces.add(p, piece_id=a.id, title=" ".join(a.args), **{k: v for k, v in fields.items() if k != "title"})
            print(f"added pieces/{x['id']}  (write the text in pieces/{x['id']}/text.md)")
        elif a.what == "show":
            x = pieces.get(_one(a))
            print("\n".join(f"{k:<13} {v}" for k, v in x.items()))
            print("\n" + pieces.read_text(x["id"]))
        elif a.what == "set":
            pid = _one(a)
            status = fields.get("status") or ("scheduled" if a.at else None)
            if a.at and "status" not in fields:
                fields["status"] = "scheduled"
            if status in pieces.USER_ONLY:
                from .cli import _user_only
                _user_only(f"Set piece {pid} to `{status}`" + (f" for {a.at}" if a.at else ""), status)
            _, after = pieces.update(pid, **fields)
            print(f"updated {pid}: {after.get('status')}" + (f", scheduled for {after['scheduled_at']}" if after.get("scheduled_at") else ""))
        elif a.what == "rm":
            x = pieces.remove(_one(a))
            print(f"removed {x['id']} (kept in pieces/.removed/{x['id']})")
        elif a.what == "open":
            x = pieces.focus(_one(a))
            from . import ui
            if a.browser:                           # start the web view if needed and bring up the desk view
                import webbrowser
                url, started = ui.ensure_running()
                webbrowser.open(url)
                print(f"{'started the web view and ' if started else ''}opened {url}: {x['project']}/{x['piece']} in the post preview")
            else:
                print(f"the web view shows {x['project']}/{x['piece']}" if ui.running() else
                      f"{x['project']}/{x['piece']} is shown when the web view opens (desktop icon, sb ui, or sb piece open ID --browser)")
        elif a.what == "export":
            r = pieces.export(_one(a), to=a.to)
            print(f"exported to {r['folder']}: {', '.join(r['files'])}")
            print("nothing was posted; posting stays your step")
        elif a.what == "due":
            rows = pieces.due()
            for x in rows:
                print(f"{x['scheduled_at']}  {x['id']}  {x.get('channel', '')}  {x.get('title', '')}")
            print(f"{len(rows)} due")
        else:                                       # check
            ids = a.args or [x["id"] for x in pieces.load()]
            bad = 0
            for pid in ids:
                found = pieces.findings(pid)
                errs, warns = found["errors"], found["warnings"]
                bad += len(errs)
                for i in found["info"]:
                    print(f"info:    {pid}: {i}")
                for w in warns:
                    print(f"warning: {pid}: {w}")
                for e in errs:
                    print(f"ERROR:   {pid}: {e}")
            print(f"{len(ids)} pieces checked, {bad} errors")
            sys.exit(1 if bad else 0)
    except (KeyError, ValueError, FileNotFoundError) as e:
        _fail(e)


def _one(a) -> str:
    if not a.args:
        sys.exit(f"usage: sb piece {a.what} ID")
    return a.args[0].replace("pieces/", "").strip("/")


def cmd_render(a):
    from . import render
    try:
        m = render.render(a.target, a.template, design_id=a.design)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as e:
        _fail(e)
    print(f"rendered {m['target']} with {m['template']} ({m['kind']}, design {m['design']}): {m['folder']}")
    for f in m["files"]:
        print("  ", f)
    for n in m.get("notes") or []:
        print("note:", n)
    if m["missing_results"]:
        print("warning: results used but not recorded:", ", ".join(m["missing_results"]))


def cmd_deliver(a):
    from . import deliver
    try:
        m = deliver.deliver(a.target, a.template, pdf=a.pdf, email=a.email, zip_it=a.zip)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as e:
        _fail(e)
    print(f"delivered {m['target']}: {m['folder']}")
    for f in m["files"]:
        print(f"   {f['file']}  ({f['from']})")
    for n in m["notes"]:
        print("note:", n)
    if m.get("zip"):
        print("zip:", m["zip"])
    if m["for_review_only"]:
        print(f"for review only: the piece has status `{m['status'] or 'none'}`; approving it is the person's decision")
    print("nothing was sent: open, check and hand on by hand")


def cmd_design(a):
    from . import assets
    try:
        if a.what == "list":
            for d in assets.designs():
                print(f"{d['id']:<20} {d['origin']:<10} {d['name']}  {d['colors']['primary']} {d['colors']['accent']}")
        elif a.what == "show":
            import yaml
            print(yaml.safe_dump(assets.design(a.id), sort_keys=False, allow_unicode=True))
        else:
            if not a.id or not a.name:
                sys.exit('usage: sb design new ID --name "Organisation"')
            d = assets.new_design(a.id, a.name)
            print(f"wrote {d / 'design.yaml'}\nedit the colours and fonts there, and put the logo files into {d}")
    except (ValueError, OSError) as e:
        _fail(e)


def cmd_template(a):
    from . import assets
    try:
        if a.what == "list":
            for t in assets.templates():
                print(f"{t['id']:<28} {t['kind']:<10} {t['origin']:<9} design {t['design'] or '-':<14} {t['title']}")
        elif a.what == "add":
            if not a.id:
                sys.exit("usage: sb template add FOLDER [--as ID]")
            print("registered", assets.add_template(a.id, a.as_id))
        elif a.what == "guide":
            if not a.id:
                sys.exit("usage: sb template guide ID")
            from . import render
            g = render.template_format(a.id)
            size = " x ".join(str(v) for v in g["size"].values())
            print(f"{g['template']}: kind {g['kind']}, design {g['design'] or '-'}" + (f", {size} px" if size else ""))
            print("a piece needs: text.md" + "".join(f", {x}" for x in g["data_files"]))
            print()
            print(g["guide"] or "(the renderer has no guide)")
        else:
            if not a.id or not a.kind:
                sys.exit('usage: sb template new ID --kind KIND [--design ID] [--title "..."]')
            d = assets.new_template(a.id, a.kind, title=a.title or "", design_id=a.design)
            print(f"wrote a starting template of kind {a.kind}: {d}")
    except (ValueError, OSError, KeyError) as e:
        _fail(e)


def cmd_pack(a):
    from . import assets
    try:
        if a.what == "install":
            done = assets.install_pack(a.folder)
            if done.get("pack"):
                p = done["pack"]
                print(f"pack {p['name']}" + (f" {p['version']}" if p["version"] else "") + f": {p['files']} files checked")
                print(f"from {p['source']} (sha256 {p['sha256'][:12]})")
            print(f"installed designs: {', '.join(done['designs']) or 'none'}; templates: {', '.join(done['templates']) or 'none'}")
            if done.get("skills"):                  # playbooks for Claude Code: where Claude Code finds them
                from .cli import _place
                from . import config
                claude = Path.home() / ".claude" / "skills"
                for name in done["skills"]:
                    how = _place(config.hub().registry / "skills" / name, claude / name)
                    print(f"skill {name} -> {claude / name}" + (" (copied: run `sb pack install` again after an update)" if how == "copied" else ""))
            manifest = _pack_manifest(a.folder)
            if (manifest or {}).get("requires"):
                from . import toolkits
                for ok, text in toolkits.requirements(manifest):
                    print(("needs  " if ok else "MISSING ") + text)
            prev = done.get("previous")
            if done.get("source_differs") and prev:
                print(f"note: the content differs from what was installed on {str(prev.get('installed', ''))[:10]} "
                      f"from {prev.get('source') or prev.get('file')}")
            if done.get("changed"):
                print("replaced, differs from what was installed: " + ", ".join(done["changed"]))
            if done.get("unchanged"):
                print("replaced, the same as installed: " + ", ".join(done["unchanged"]))
        else:
            print("wrote", assets.export_pack(a.folder, designs_=a.design or [], templates_=a.template or [], skills_=a.skill or []))
    except (ValueError, OSError) as e:
        _fail(e)


def _pack_manifest(source) -> dict:
    """pack.yaml of a pack folder or zip (empty when there is none)."""
    import yaml
    p = Path(source)
    try:
        if p.is_dir():
            f = p / "pack.yaml"
            return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.is_file() else {}
        import zipfile
        with zipfile.ZipFile(p) as z:
            name = next((n for n in z.namelist() if n.rstrip("/").split("/")[-1] == "pack.yaml" and n.count("/") <= 1), None)
            return (yaml.safe_load(z.read(name).decode("utf-8")) or {}) if name else {}
    except (OSError, ValueError, KeyError, yaml.YAMLError):
        return {}


def config_path():
    from . import config
    return config.user_config_path()


def cmd_plugin(a):
    from . import plugins
    if a.what in ("add", "remove"):
        if not a.folder:
            sys.exit(f"usage: sb plugin {a.what} FOLDER")
        try:
            now = plugins.add_folder(a.folder) if a.what == "add" else plugins.remove_folder(a.folder)
        except (ValueError, OSError) as e:
            _fail(e)
        print(f"plugin folders ({config_path()}): " + (", ".join(now) or "none"))
    reg = plugins.load(fresh=True)
    for p in reg.plugins:
        print(f"{p.name:<14} {p.package} {p.version}  " + (f"ERROR: {p.error}" if p.error else
              f"renders: {', '.join(p.renderers) or '-'}; commands: {', '.join(p.commands) or '-'}"
              + (f"; charts: {', '.join(p.chart_renderers)}" if p.chart_renderers else "")
              + (f"; toolkits: {', '.join(p.toolkits)}" if p.toolkits else "")
              + (f"; brings {len(p.packs)} pack" if p.packs else "")))
    print(f"{len(reg.plugins)} plugins; formats: {', '.join(sorted(reg.renderers))}")
    if not reg.plugins:
        print("plugins are separate packages (see the plugins/ folder of the checkout): uv pip install -e plugins/<name>")


def cmd_job(a):
    from . import jobs
    try:
        if a.what == "list":
            for j in jobs.listing():
                if j.get("error"):
                    print(f"{j['id']:<22} ERROR: {j['error']}")
                    continue
                print(f"{j['id']:<22} every {j['every']:<5} {'due' if j['due'] else 'on' if j['enabled'] else 'off':<4} "
                      f"last {j['last_run'] or 'never':<26} {j['last_status'] or '':<7} {j['title']}")
        elif a.what == "add":
            if not a.id or not a.run or not a.every:
                sys.exit('usage: sb job add ID --run "pipelines/x/pipeline.py" --every 6h [--table schema.table] [--source ID]')
            print("wrote", jobs.add(a.id, run=a.run, every=a.every, title=a.title or "", table=a.table or "", source=a.source or ""))
        elif a.what == "run":
            lines = jobs.run_due() if a.due else [jobs.run(a.id)] if a.id else sys.exit("usage: sb job run ID | --due")
            for x in lines:
                print(f"{x['job']}: {x['status']} in {x['seconds']} s" + (f"\n{x['message']}" if x["status"] != "ok" else ""))
            if not lines:
                print("nothing is due")
            sys.exit(1 if any(x["status"] != "ok" for x in lines) else 0)
        elif a.what == "log":
            for x in jobs.log(40):
                print(f"{x['at']}  {x['job']:<22} {x['status']:<7} {x['seconds']} s")
        else:
            print(jobs.schedule_hint())
    except (KeyError, ValueError, OSError) as e:
        _fail(e)


def cmd_sql(a):
    import polars as pl

    from . import connections
    try:
        out = connections.sql(a.target, a.query, limit=a.limit)
    except Exception as e:                          # database errors come in many types; all are the user's to read
        _fail(e)
    pl.Config.set_tbl_rows(a.limit)
    pl.Config.set_fmt_str_lengths(60)
    print(pl.DataFrame(out["rows"], schema=out["columns"], orient="row") if out["rows"] else "no rows")
    print(f"{out['row_count']} rows" + (f" (first {a.limit} shown)" if out["truncated"] else "") + f", {out['seconds']} s")


def cmd_mcp(a):
    from . import connections
    try:
        if a.what == "list":
            for s in connections.mcp_list():
                env = ", ".join(f"{e['name']}{'' if e['set'] else ' (not set)'}" for e in s["env"])
                print(f"{s['name']:<20} {s['transport']:<6} {s.get('url') or ' '.join([s.get('command', ''), *s.get('args', [])])}" + (f"  env: {env}" if env else ""))
        elif a.what == "add":
            if not a.names:
                sys.exit('usage: sb mcp add NAME --url URL | --command "program args" [--env VAR ...]')
            print("wrote", connections.mcp_add(a.names[0], url=a.url, command=a.command, env=a.env, note=a.note or "", source=a.source or ""))
        elif a.what == "rm":
            connections.mcp_remove(a.names[0] if a.names else sys.exit("usage: sb mcp rm NAME"))
            print("removed")
        else:
            f, names = connections.mcp_link(a.names or None)
            print(f"wrote {f}: {', '.join(names)}\nClaude Code asks once before it uses a server from this file.")
    except (KeyError, ValueError, OSError) as e:
        _fail(e)


def add_parsers(sub) -> None:
    s = sub.add_parser("doc"); s.add_argument("file"); s.add_argument("--title"); s.add_argument("--publisher")
    s.add_argument("--author"); s.add_argument("--date"); s.add_argument("--note")
    s.add_argument("--new", action="store_true", help="register again even if the same bytes are already a source")
    s.set_defaults(f=cmd_doc)
    s = sub.add_parser("piece"); s.add_argument("what", choices=["list", "add", "show", "set", "rm", "check", "due", "export", "open"])
    s.add_argument("args", nargs="*"); s.add_argument("--id"); s.add_argument("--at", help='when to publish, e.g. "2026-11-20 08:30"')
    s.add_argument("--to", help="export: the folder to export into (default: export.dir in project.yaml)")
    s.add_argument("--browser", action="store_true", help="open: also open the web view in the browser (started if it is not running)")
    s.add_argument("--self-citation", dest="self_citation", choices=["true", "false"],
                   help="set: the piece may cite the desk's own work (own.publishers), only where the person asked for it")
    for opt in ("title", "kind", "template", "design", "status", "lang", "channel", "note", "prompt", "url"):
        s.add_argument(f"--{opt}")
    s.set_defaults(f=cmd_piece)
    s = sub.add_parser("render"); s.add_argument("target"); s.add_argument("--template", required=True); s.add_argument("--design")
    s.set_defaults(f=cmd_render)
    s = sub.add_parser("deliver", help="render, convert and collect a piece or deliverable into one folder (nothing is sent)")
    s.add_argument("target"); s.add_argument("--template", action="append", default=[], help="repeatable; default: the piece's template")
    s.add_argument("--pdf", action="store_true", help="every .docx also as .pdf (Word plugin)")
    s.add_argument("--email", nargs="?", const="", default=None, metavar="ADDRESS", help="also an unsent e-mail draft (.eml)")
    s.add_argument("--zip", action="store_true", help="also the folder as .zip")
    s.set_defaults(f=cmd_deliver)
    s = sub.add_parser("design"); s.add_argument("what", choices=["list", "show", "new"]); s.add_argument("id", nargs="?")
    s.add_argument("--name"); s.set_defaults(f=cmd_design)
    s = sub.add_parser("template"); s.add_argument("what", choices=["list", "add", "new", "guide"]); s.add_argument("id", nargs="?")
    s.add_argument("--as", dest="as_id"); s.add_argument("--kind"); s.add_argument("--design"); s.add_argument("--title")
    s.set_defaults(f=cmd_template)
    s = sub.add_parser("pack"); s.add_argument("what", choices=["install", "export"]); s.add_argument("folder")
    s.add_argument("--design", action="append"); s.add_argument("--template", action="append")
    s.add_argument("--skill", action="append", help="export: a playbook for agents installed from a pack"); s.set_defaults(f=cmd_pack)
    s = sub.add_parser("plugin", help="installed plugins; add/remove a plugin folder (a private plugin kept outside the environment)")
    s.add_argument("what", choices=["list", "add", "remove"], nargs="?", default="list"); s.add_argument("folder", nargs="?")
    s.set_defaults(f=cmd_plugin)
    s = sub.add_parser("job"); s.add_argument("what", choices=["list", "add", "run", "log", "schedule"]); s.add_argument("id", nargs="?")
    s.add_argument("--run"); s.add_argument("--every"); s.add_argument("--title"); s.add_argument("--table"); s.add_argument("--source")
    s.add_argument("--due", action="store_true"); s.set_defaults(f=cmd_job)
    s = sub.add_parser("sql"); s.add_argument("target"); s.add_argument("query"); s.add_argument("--limit", type=int, default=50)
    s.set_defaults(f=cmd_sql)
    s = sub.add_parser("mcp"); s.add_argument("what", choices=["list", "add", "rm", "link"]); s.add_argument("names", nargs="*")
    s.add_argument("--url"); s.add_argument("--command"); s.add_argument("--env", action="append"); s.add_argument("--note")
    s.add_argument("--source"); s.set_defaults(f=cmd_mcp)
    from . import plugins
    for name, (setup, run, help_, _plugin) in plugins.load().commands.items():
        s = sub.add_parser(name, help=help_)
        setup(s)
        s.set_defaults(f=run)
