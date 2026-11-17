"""Commands beyond the study workflow: pieces, rendering, designs and templates, jobs, connections.

  sb new SLUG --title "..." --kind desk      ongoing research on a topic (pieces instead of a paper)
  sb doc FILE --title "..." [--publisher P]  register a local document as a source (W-xxxx), archived
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


def document_text(body: bytes, name: str) -> str:
    """Readable text of an archived document, by its file name (docx, pptx, html, text)."""
    import html as htmlmod
    import io
    import re
    import zipfile
    suffix = Path(name).suffix.lower()
    if suffix in {".docx", ".pptx"}:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            parts = [n for n in z.namelist() if re.fullmatch(r"word/document\.xml|ppt/slides/slide\d+\.xml", n)]
            xml = "\n".join(z.read(n).decode("utf-8", errors="replace") for n in sorted(parts))
        xml = re.sub(r"</w:p>|</a:p>|<w:br[^>]*/>", "\n", xml)
        return htmlmod.unescape(re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", xml)))
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
    sid = ledger.add_source({"title": a.title or f.stem, "url": f"file:{f.name}", "publisher": a.publisher or "",
                             "accessed": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sha256": ref.sha256,
                             "raw": ref.path, "file": f.name, "kind": "document", "note": a.note or "",
                             **({"date": a.date} if a.date else {}), **({"author": a.author} if a.author else {})})
    print(f"{sid}  {f.name}\n      archived raw/{ref.path}  (cite as [@{sid}]; read it with `sb source {sid}`)")


def cmd_piece(a):
    from . import config, pieces
    fields = {k: getattr(a, k) for k in ("title", "kind", "template", "design", "status", "lang", "channel", "note", "prompt", "url")
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
        elif a.what == "due":
            rows = pieces.due()
            for x in rows:
                print(f"{x['scheduled_at']}  {x['id']}  {x.get('channel', '')}  {x.get('title', '')}")
            print(f"{len(rows)} due")
        else:                                       # check
            ids = a.args or [x["id"] for x in pieces.load()]
            bad = 0
            for pid in ids:
                errs, warns = pieces.check(pid)
                bad += len(errs)
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
        else:
            if not a.id or not a.kind:
                sys.exit('usage: sb template new ID --kind KIND [--design ID] [--title "..."]')
            d = assets.new_template(a.id, a.kind, title=a.title or "", design_id=a.design)
            print(f"wrote a starting template of kind {a.kind}: {d}")
    except (ValueError, OSError) as e:
        _fail(e)


def cmd_pack(a):
    from . import assets
    try:
        if a.what == "install":
            done = assets.install_pack(a.folder)
            if done.get("pack"):
                p = done["pack"]
                print(f"pack {p['name']}" + (f" {p['version']}" if p["version"] else "") + f": {p['files']} files checked")
            print(f"installed designs: {', '.join(done['designs']) or 'none'}; templates: {', '.join(done['templates']) or 'none'}")
            if done.get("replaced"):
                print("replaced (were installed before): " + ", ".join(done["replaced"]))
        else:
            print("wrote", assets.export_pack(a.folder, designs_=a.design or [], templates_=a.template or []))
    except (ValueError, OSError) as e:
        _fail(e)


def cmd_plugin(a):
    from . import plugins
    reg = plugins.load()
    for p in reg.plugins:
        print(f"{p.name:<14} {p.package} {p.version}  " + (f"ERROR: {p.error}" if p.error else
              f"renders: {', '.join(p.renderers) or '-'}; commands: {', '.join(p.commands) or '-'}"
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
    s.add_argument("--author"); s.add_argument("--date"); s.add_argument("--note"); s.set_defaults(f=cmd_doc)
    s = sub.add_parser("piece"); s.add_argument("what", choices=["list", "add", "show", "set", "rm", "check", "due"])
    s.add_argument("args", nargs="*"); s.add_argument("--id"); s.add_argument("--at", help='when to publish, e.g. "2026-11-20 08:30"')
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
    s = sub.add_parser("template"); s.add_argument("what", choices=["list", "add", "new"]); s.add_argument("id", nargs="?")
    s.add_argument("--as", dest="as_id"); s.add_argument("--kind"); s.add_argument("--design"); s.add_argument("--title")
    s.set_defaults(f=cmd_template)
    s = sub.add_parser("pack"); s.add_argument("what", choices=["install", "export"]); s.add_argument("folder")
    s.add_argument("--design", action="append"); s.add_argument("--template", action="append"); s.set_defaults(f=cmd_pack)
    s = sub.add_parser("plugin"); s.add_argument("what", choices=["list"], nargs="?", default="list"); s.set_defaults(f=cmd_plugin)
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
