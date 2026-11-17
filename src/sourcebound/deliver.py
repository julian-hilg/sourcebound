"""Delivery: everything a person needs to hand a piece or deliverable on, in one folder.

    sb deliver TARGET [--template ID ...] [--pdf] [--email [ADDRESS]] [--zip]

renders TARGET with each template, adds converted formats (`--pdf`: every .docx also as .pdf,
through a converter a plugin brings), and copies the files into

    <project>/dist/deliver/<name>-<YYYYMMDD-HHMM>/
        <the rendered files>  ...
        <name>.eml            with --email: an unsent e-mail (subject, text, attachments) to open,
                              check and send by hand; Outlook opens it as a draft (X-Unsent)
        MANIFEST.json         what is in the folder: target, templates, commit, results shown,
                              status of the piece, each file with size and sha256
        README.txt            the same for a person

Nothing leaves the machine: Sourcebound does not send, post or upload. The delivery folder is
not a publication either (`sb publish` is). A piece that is not `approved` yet is delivered for
review only, and the manifest and README say so.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

from . import config, plugins, render

MIME = {".pdf": ("application", "pdf"), ".docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ".png": ("image", "png"), ".md": ("text", "markdown"), ".txt": ("text", "plain"), ".html": ("text", "html")}


def _sha(f: Path) -> str:
    h = hashlib.sha256()
    with f.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def converters() -> dict[tuple, plugins.Converter]:
    return plugins.load().converters


def deliver(target: str, templates: list[str], *, pdf: bool = False, email: str | None = None,
            to: str = "", zip_it: bool = False, project: config.Project | None = None,
            now: datetime | None = None) -> dict:
    """Render, convert and collect; returns the manifest (with `folder`)."""
    p = project or config.project()
    doc = render.document(target, p)
    templates = templates or [t for t in [doc.meta.get("template")] if t]
    if not templates:
        raise ValueError("no template: name one with --template (the piece has no default template)")
    want = [(".docx", ".pdf")] if pdf else []
    missing = [f"{s} -> {t}" for s, t in want if (s, t) not in converters()]
    if missing:
        raise RuntimeError(f"no converter for {', '.join(missing)} is installed (the Word plugin brings .docx -> .pdf: "
                           "uv sync --extra word)")
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M")
    out = p.root / "dist" / "deliver" / f"{doc.name}-{stamp}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    files, notes, rendered = [], [], []
    for tid in templates:
        m = render.render(target, tid, project=p)
        rendered.append({k: m[k] for k in ("template", "kind", "design", "at", "commit", "results", "missing_results")})
        notes += [f"{tid}: {n}" for n in m.get("notes") or []]
        for rel in m["files"]:
            src = Path(m["folder"]) / rel
            if src.suffix.lower() in (".json",) or not src.is_file():
                continue
            dest = out / (src.name if len(templates) == 1 else f"{tid}__{src.name}")
            shutil.copy2(src, dest)
            files.append({"file": dest.name, "template": tid, "from": "render"})
            for s, t in want:
                if src.suffix.lower() == s:
                    conv = converters()[(s, t)]
                    made = conv.fn(dest, dest.with_suffix(t))
                    made, more = (made if isinstance(made, tuple) else (made, []))
                    files.append({"file": Path(made).name, "template": tid, "from": f"{conv.plugin}: {s} -> {t}"})
                    notes += [f"{Path(made).name}: {n}" for n in more]
    status = str(doc.meta.get("status") or "") if doc.kind == "piece" else ""
    if email is not None:
        eml = out / f"{doc.name}.eml"
        attach = [out / f["file"] for f in files if Path(f["file"]).suffix.lower() == ".pdf"] or \
                 [out / f["file"] for f in files if Path(f["file"]).suffix.lower() in (".docx", ".png")]
        eml.write_bytes(email_draft(doc, attach, to=email or to))
        files.append({"file": eml.name, "template": "", "from": "e-mail draft (unsent)"})
    for f in files:
        path = out / f["file"]
        f.update(bytes=path.stat().st_size, sha256=_sha(path))
    manifest = {"sourcebound_delivery": 1, "target": f"{'pieces' if doc.kind == 'piece' else 'deliverables'}/{doc.name}",
                "title": doc.title, "status": status, "for_review_only": doc.kind == "piece" and status not in ("approved", "scheduled", "published"),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": render._commit(p.root),
                "renders": rendered, "files": files, "notes": notes}
    config.write_atomic(out / "MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (out / "README.txt").write_text(readme(manifest), encoding="utf-8")
    if zip_it:
        z = out.with_suffix(".zip")
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(out.iterdir()):
                zf.write(f, f"{out.name}/{f.name}")
        manifest["zip"] = str(z)
    return {**manifest, "folder": str(out)}


def email_draft(doc: render.Document, attachments: list[Path], *, to: str = "") -> bytes:
    """An unsent e-mail (RFC 5322 with `X-Unsent: 1`): subject, the text as plain text, the attachments.

    Opened in Outlook it is a draft to check and send; nothing is sent from here."""
    msg = EmailMessage()
    msg["Subject"] = doc.title
    if to:
        msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["X-Unsent"] = "1"
    msg.set_content(render.plain_text(doc))
    for f in attachments:
        main, sub = MIME.get(f.suffix.lower(), ("application", "octet-stream"))
        msg.add_attachment(f.read_bytes(), maintype=main, subtype=sub, filename=f.name)
    return bytes(msg)


def readme(m: dict) -> str:
    lines = [f"{m['title']}", f"{m['target']}, delivered {m['at']}" + (f" from commit {m['commit']}" if m["commit"] else ""), ""]
    if m["for_review_only"]:
        lines += [f"FOR REVIEW: the piece has status `{m['status'] or 'none'}`, not `approved`.", ""]
    lines += ["Files:"] + [f"  {f['file']:<48} {f['bytes']:>10,} bytes   {f['from']}" for f in m["files"]]
    if m["notes"]:
        lines += ["", "Notes:"] + [f"  - {n}" for n in m["notes"]]
    lines += ["", "Nothing was sent or published. MANIFEST.json lists each file with its sha256."]
    return "\n".join(lines) + "\n"
