"""What a LinkedIn post needs besides the slides: the text, its limits, a preview, a bundle to post by hand.

Nothing here talks to LinkedIn.  Posting is done by the person: there are no credentials in
Sourcebound, and publishing is the person's decision.  An API publisher would be one more
function here, called only from a command the person runs.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from sourcebound import config, pieces, render

from . import deck as decks

LIMIT = 3000                # characters of a post's text
VISIBLE = 210               # about what shows before "...more" on a desktop feed; about 140 on a phone
VISIBLE_PHONE = 140
MAX_HASHTAGS = 5
MAX_SLIDES = 20             # images in one post; a document post takes more, but nobody reads more


def post_text(doc) -> str:
    """The post as plain text: no markup, sources numbered in the text and named at the end.

    A source is named as a reader of a post needs it: who and what, no address (links in a
    post's text cost reach, and the addresses are long).  The piece's first heading repeats
    the title and is left out.
    """
    order: list[str] = []

    def cite(keys, locator, textual):
        order.extend(k for k in keys if k not in order)
        nums = ", ".join(str(order.index(k) + 1) for k in keys)
        if textual:
            who = render.cite_label(keys[0], doc)
            return f"{who[0] if who else keys[0]} [{nums}]"
        return f"[{nums}]"
    s = render.fill(doc.text, doc, cite=cite)
    s = re.sub(r"(?m)^#{1,6}\s+(.*?)(?:\s*\{#[^}]*\})?$", r"\1", s)
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)(?:\{#[^}]*\})?", "", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\1", s)
    s = re.sub(r"`([^`\n]*)`", r"\1", s)
    s = re.sub(r"\{\{(?:ref|table):[^}]*\}\}", "", s)
    s = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", s)).strip()
    first, _, rest = s.partition("\n")
    if first.strip() == doc.title.strip() and rest.strip():
        s = rest.lstrip("\n")
    if order:
        # sources go before the hashtags, which close a post
        body, tags = s, ""
        m = re.search(r"\n\n((?:#\w+\s*)+)$", s)
        if m:
            body, tags = s[:m.start()], m.group(1).strip()
        head = "Quellen:" if doc.german else "Sources:"
        s = body + f"\n\n{head}\n" + "\n".join(f"{n}. {decks._source_item(k, doc)}" for n, k in enumerate(order, 1)) + (f"\n\n{tags}" if tags else "")
    return s + "\n"


def hashtags(text: str) -> list[str]:
    return re.findall(r"(?<![\w&])#[^\W\d_][\w]*", text)


def visible_part(text: str, limit: int = VISIBLE) -> tuple[str, bool]:
    """What shows before the reader clicks "more": the first lines up to about `limit` characters."""
    head = "\n".join(text.strip().split("\n")[:3])
    if len(head) <= limit and head == text.strip():
        return head, False
    if len(head) > limit:
        head = head[:limit].rsplit(" ", 1)[0]
    return head.rstrip(), True


def preview(doc, slides: list[dict], images: list[Path], document: Path | None, deck: dict, layout: dict) -> dict:
    text = post_text(doc)
    shown, cut = visible_part(text)
    return {"format": "sourcebound-preview", "version": 1, "channel": "linkedin",
            "title": doc.title, "lang": doc.lang,
            "text": text, "characters": len(text), "limit": LIMIT,
            "visible": shown, "more": cut, "hashtags": hashtags(text),
            "width": deck["width"], "height": deck["height"],
            "slides": [{"file": images[i].name if i < len(images) else None, "title": str(s.get("title") or ""),
                        "alt": decks.alt_text(s)} for i, s in enumerate(slides)],
            "document": document.name if document else None,
            "remedies": layout.get("remedies", []), "browser": layout.get("browser")}


def check(piece_id: str, project=None) -> tuple[list[str], list[str]]:
    """(errors, warnings) of a piece as a LinkedIn post: text limits, hashtags, slides and their sources."""
    p = project or config.project()
    doc = render.from_piece(p, piece_id)
    errs, warns = [], []
    text = post_text(doc)
    if not text.strip():
        errs.append("the post has no text (pieces/<id>/text.md)")
    if len(text) > LIMIT:
        errs.append(f"the text has {len(text)} characters; LinkedIn takes {LIMIT}")
    hook = text.strip().split("\n")[0]
    if len(hook) > VISIBLE:
        warns.append(f"the first line has {len(hook)} characters; about {VISIBLE} show before “more” ({VISIBLE_PHONE} on a phone)")
    elif len(hook) > VISIBLE_PHONE:
        warns.append(f"the first line has {len(hook)} characters; on a phone about {VISIBLE_PHONE} show before “more”")
    tags = hashtags(text)
    if len(tags) > MAX_HASHTAGS:
        warns.append(f"{len(tags)} hashtags; more than {MAX_HASHTAGS} read as spam")
    if "?" in re.sub(r"\?[a-z0-9_.]+", "", "") or re.search(r"\?[a-z][\w]*\.[\w.]+", text):
        errs.append("the text shows a result that was never recorded (?key)")
    data = doc.data.get("slides")
    if not data:
        warns.append("no slides.yaml: the post would go out as text only")
    else:
        from sourcebound import assets
        try:
            design = assets.design(doc.meta.get("design") or None)
        except FileNotFoundError as e:
            errs.append(str(e))
            design = assets.design(None)
        errs += decks.problems(data, doc, design)
        n = len(data.get("slides") or []) if isinstance(data, dict) else 0
        if n > MAX_SLIDES:
            warns.append(f"{n} slides; an image post takes {MAX_SLIDES}, and readers rarely go past 10")
    rs = [m for m in render.renders(pieces.folder(p, piece_id) / "render") if m.get("kind") == "slides"]
    if data and not rs:
        warns.append("the slides are not rendered yet: sb render <piece> --template <slides template>")
    for m in rs:
        changed = render.stale(m, doc.results)
        if changed:
            warns.append(f"render {m['template']} shows older values of {', '.join(changed[:5])}: render again")
    return errs, warns


# The steps to post by hand, in the language of the post (de or en; anything else gets en).
STEPS = {
    "en": {
        "head": "How to post this (by hand; Sourcebound does not post)",
        "open": "Open LinkedIn and start a post.",
        "paste": "Paste the text from post.txt.",
        "slides": ("Add the slides, one of two ways:\n"
                   "   - as a document: \"Add a document\", choose {pdf}, give it a title. Readers swipe through the pages.\n"
                   "   - as images: \"Add media\", choose the PNG files in order ({first} ... {last}).\n"
                   "     Give each image its alternative text from alt-texts.txt."),
        "image": "Add the image: \"Add media\", choose {first}, and give it the alternative text from alt-texts.txt.",
        "check": "Check the preview, then post or schedule.",
        "record": "Record it: sb piece set {piece} --status published --url <the post's address>",
        "foot": "Text: {chars} of {limit} characters. Slides: {n}. Template: {template}, design: {design}, rendered {at}.",
    },
    "de": {
        "head": "So wird der Beitrag gepostet (von Hand; Sourcebound postet nicht)",
        "open": "LinkedIn öffnen und einen Beitrag beginnen.",
        "paste": "Den Text aus post.txt einfügen.",
        "slides": ("Die Folien hinzufügen, auf einem von zwei Wegen:\n"
                   "   - als Dokument: {pdf} als Dokument hochladen und ihm einen Titel geben. Die Leser blättern durch die Seiten.\n"
                   "   - als Bilder: die PNG-Dateien in dieser Reihenfolge als Medien hochladen ({first} ... {last}).\n"
                   "     Jedem Bild seinen Alternativtext aus alt-texts.txt geben."),
        "image": "Das Bild hinzufügen: {first} als Medium hochladen und ihm den Alternativtext aus alt-texts.txt geben.",
        "check": "Die Vorschau prüfen, dann posten oder planen.",
        "record": "Festhalten: sb piece set {piece} --status published --url <Adresse des Beitrags>",
        "foot": "Text: {chars} von {limit} Zeichen. Folien: {n}. Vorlage: {template}, Design: {design}, gerendert {at}.",
    },
}


def steps(lang: str | None, **v) -> str:
    """README.txt of a bundle: the steps to post it by hand, in the post's language."""
    t = STEPS["de" if str(lang or "").lower().startswith("de") else "en"]
    add = t["slides"] if v.get("pdf") and v.get("n", 0) > 1 else t["image"]
    lines = [t["open"], t["paste"], add, t["check"], t["record"]]
    body = "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))
    return (t["head"] + "\n\n" + body + "\n\n" + t["foot"] + "\n").format(**v)


def bundle(piece_id: str, *, template: str | None = None, out: str | None = None, project=None) -> Path:
    """A folder with everything to post by hand: text, images, carousel PDF, alternative texts, the steps."""
    p = project or config.project()
    rs = [m for m in render.renders(pieces.folder(p, piece_id) / "render") if m.get("kind") == "slides"
          and (template is None or m["template"] == template)]
    if not rs:
        raise FileNotFoundError(f"no slides render of {piece_id}" + (f" with template {template}" if template else "")
                                + ": sb render " + piece_id + " --template <slides template>")
    m = max(rs, key=lambda r: r["at"])
    src = Path(m["folder"])
    pv = json.loads((src / "preview.json").read_text(encoding="utf-8"))
    if not any(s["file"] for s in pv["slides"]):
        raise FileNotFoundError("the render has no images (no Chromium was found when it ran): install Chrome or Edge and render again")
    dest = Path(out).expanduser().resolve() if out else src / "post"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "post.txt").write_text(pv["text"], encoding="utf-8")
    names = [s["file"] for s in pv["slides"] if s["file"]]
    for name in [*names, pv["document"]]:
        if name and (src / name).exists():
            shutil.copy2(src / name, dest / name)
    (dest / "alt-texts.txt").write_text("\n\n".join(f"{s['file']}\n{s['alt']}" for s in pv["slides"] if s["file"]) + "\n", encoding="utf-8")
    deck = (render.from_piece(p, piece_id).data.get("slides") or {}).get("deck") or {}
    lang = deck.get("lang") or pv.get("lang") or p.lang         # the deck's language, else the piece's, else the project's
    (dest / "README.txt").write_text(steps(lang, pdf=pv["document"], first=names[0], last=names[-1], piece=piece_id, chars=pv["characters"],
                                           limit=pv["limit"], n=len(names), template=m["template"], design=m["design"], at=m["at"]),
                                     encoding="utf-8")
    return dest
