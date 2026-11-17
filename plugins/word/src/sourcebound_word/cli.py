"""`sb word ...`: the commands around a Word file and a Word template."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def setup(parser) -> None:
    parser.add_argument("what", choices=["status", "refresh", "pull", "inspect", "adopt", "pdf"])
    parser.add_argument("--engine", choices=["word", "libreoffice"], help="pdf: which program converts (default: the first available)")
    parser.add_argument("file", help="the Word file (.docx; for inspect and adopt also .dotx or .dotm)")
    parser.add_argument("--project", help="the project folder, if the file is not inside it")
    parser.add_argument("--id", help="adopt: the id of the new template")
    parser.add_argument("--design", help="adopt: the design the template belongs to")
    parser.add_argument("--title", help="adopt: a title for listings")
    parser.add_argument("--out", help="pull: where to write the Markdown (default: next to the source); pdf: the PDF file")
    parser.add_argument("--sources", action="store_true", help="refresh: regenerate a source list that was edited by hand")
    parser.add_argument("--json", action="store_true", help="print the report as data")


def _lines(title: str, rows: list[str], limit: int = 12) -> None:
    if rows:
        print(f"{title} ({len(rows)}):")
        for r in rows[:limit]:
            print("  ", r)
        if len(rows) > limit:
            print(f"   ... and {len(rows) - limit} more")


def run(a) -> None:
    from . import roundtrip, template
    try:
        if a.what == "pdf":
            from . import pdf
            rep = pdf.to_pdf(Path(a.file), a.out, engine=a.engine)
            if a.json:
                return print(json.dumps(rep, indent=2, ensure_ascii=False))
            print(f"wrote {rep['pdf']} ({rep['engine']}, {rep['seconds']} s)")
            for n in rep["notes"]:
                print("note:", n)
            return
        if a.what == "inspect":
            rep = template.inspect(Path(a.file).expanduser())
            if a.json:
                return print(json.dumps(rep, indent=2, ensure_ascii=False))
            print(f"{rep['file']}: {rep['body_paragraphs']} paragraphs with text, {rep['sections']} sections, {rep['content_controls']} content controls"
                  + ("; a template (.dotx/.dotm): rendered files are plain .docx" if rep["was_template"] else "")
                  + ("; its macros are left out of rendered files" if rep["macros"] else ""))
            print("styles used in the body: " + (", ".join(f"{k} ({n})" for k, n in list(rep["used_in_body"].items())[:10]) or "none"))
            own = sorted(k for k, v in rep["styles"].items() if not v["builtin"] and v["type"] in ("paragraph", "table"))
            print("the template's own styles: " + (", ".join(own) or "none"))
            print("\nproposed mapping (template.yaml, `styles:`):")
            for role, name in rep["mapping"].items():
                also = rep["other_candidates"].get(role) or []
                print(f"  {role:<15} {name or '-- none found: ' + template_fallback(role)}" + (f"      (or: {', '.join(also)})" if also else ""))
            print(f"\ncontent marker {template.MARKER}: " + ("found" if rep["marker"] else
                  "not in the file: the text is appended at the end. Type {{content}} on a line of its own where the text should start."))
            print("placeholders found: " + (", ".join("{{%s}}" % p for p in rep["placeholders"]) or
                  "none ({{title}}, {{subtitle}}, {{author}}, {{date}} are filled in where the file has them)"))
        elif a.what == "adopt":
            if not a.id:
                sys.exit('usage: sb word adopt FILE --id ID [--design ID] [--title "..."]')
            from sourcebound import assets, config
            if not assets.ID.fullmatch(a.id):
                sys.exit("template id: lowercase letters, digits, - and _")
            dest, rep = template.adopt(Path(a.file), config.hub().registry, a.id, assets.design(a.design), title=a.title or "")
            print(f"registered template {a.id}: {dest}")
            if rep["missing_roles"]:
                print("no style found for: " + ", ".join(rep["missing_roles"]) + f"\n  edit `styles:` in {dest / 'template.yaml'} (sb word inspect lists the file's styles)")
            if not rep["marker"]:
                print("the file has no {{content}} line: the text will be appended at the end")
            print(f"try it: sb render <piece> --template {a.id}")
        elif a.what == "status":
            rep = roundtrip.status(Path(a.file), a.project)
            if a.json:
                return print(json.dumps(rep, indent=2, ensure_ascii=False))
            p = rep["paragraphs"]
            print(f"{Path(rep['file']).name}: rendered {rep['rendered_at']} from {rep['target']} (template {rep['template']})"
                  + (f", refreshed {rep['refreshed_at']}" if rep["refreshed_at"] else ""))
            print(f"paragraphs: {p['unchanged']} unchanged, {len(p['changed'])} changed, {len(p['added'])} added, "
                  f"{len(p['deleted'])} deleted, {len(p['moved'])} moved")
            _lines("changed", [f"{x['was']}\n      -> {x['now']}" for x in p["changed"]])
            _lines("added", p["added"])
            _lines("deleted", p["deleted"])
            _lines("moved", p["moved"])
            _lines("numbers out of date (sb word refresh updates them)", [f"{x['key']}: shows {x['shown']}, recorded {x['recorded']}" for x in rep["stale"]])
            _lines("controls typed over (kept as typed; no longer follow the results)", [f"{x['tag']}: {x['was']} -> {x['now']}" for x in rep["typed_over"]])
            _lines("controls removed", [f"{x['tag']}" + (f" ({x['times']} times)" if x["times"] > 1 else "") for x in rep["removed_controls"]])
            _lines("results no longer recorded", rep["missing_results"])
            _lines("sources no longer registered", rep["unknown_sources"])
            s = rep["sources_list"]
            if s["expected"] and not s["present"]:
                print("the source list was removed")
            elif s["edited"]:
                print("the source list was edited by hand")
            t = rep["tracked_changes"]
            if t["insertions"] or t["deletions"]:
                print(f"tracked changes: {t['insertions']} insertions, {t['deletions']} deletions (read as if all were accepted)")
            if rep.get("problem"):
                print("warning:", rep["problem"])
        elif a.what == "refresh":
            rep = roundtrip.refresh(Path(a.file), a.project, sources=a.sources)
            if a.json:
                return print(json.dumps(rep, indent=2, ensure_ascii=False))
            for c in rep["changes"]:
                print(f"{c['what']}: {c['key'] + ': ' if c['key'] else ''}{c['from']} -> {c['to']}")
            for k in rep["kept"]:
                print(f"kept as typed: {k['key']}: {k['typed']} (rendered as {k['rendered']})")
            if rep["note"]:
                print("note:", rep["note"])
            _lines("sources no longer registered", rep["unknown_sources"])
            print(f"{len(rep['changes'])} changes" + ("" if rep["changes"] else ": the file is up to date and was not written"))
        else:
            rep = roundtrip.pull(Path(a.file), a.project, a.out)
            if a.json:
                return print(json.dumps(rep, indent=2, ensure_ascii=False))
            print(f"wrote {rep['written']}")
            print(f"blocks: {rep['unchanged']} unchanged, {rep['changed']} changed, {rep['added']} added, {rep['deleted']} deleted, {rep['moved']} moved")
            for n in rep["notes"]:
                print("note:", n)
            _lines("links to results or sources that are gone from the file", [x["tag"] for x in rep["removed_controls"]])
            if rep["diff"]:
                print("\n".join(rep["diff"]))
            print("the source text was not changed: compare, then take over what you want")
    except (ValueError, KeyError, FileNotFoundError, FileExistsError, RuntimeError) as e:
        sys.exit(str(e).strip("'\""))


def template_fallback(role: str) -> str:
    return {"bullet": "bullets are typed (a bullet and a tab)", "numbered": "numbers are typed", "code": "style `SB Code` is added to rendered files",
            "source": "style `SB Source` is added to rendered files", "table": "style `SB Table` is added to rendered files",
            "quote": "indented body text", "caption": "body text", "title": "no title line is added",
            "subtitle": "not used", "figure_caption": "the caption style", "table_caption": "the caption style",
            "table_note": "the caption style", "table_text": "the table style's own text"}.get(role, "bold body text" if role.startswith("heading") else "the file's default paragraph style")
