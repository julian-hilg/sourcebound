"""Pieces: small outputs of ongoing research (a post, a note, a trade idea, a briefing).

    pieces/<id>/piece.yaml     what it is: title, kind, template, status, schedule
    pieces/<id>/text.md        the text, in the handover notation ({{result:key}}, [@W-0001])
    pieces/<id>/*.yaml         structured content a template needs (e.g. slides.yaml)
    pieces/<id>/render/        what `sb render` wrote, one folder per template

A piece needs no paper, no hypotheses and no freeze.  It still follows "no source, no claim":
every source it cites is registered in the project's ledger (an archived web page, a document
brought in with `sb doc`, a Zotero key), and every recorded number comes in as
`{{result:key}}`.  `sb piece check` reports what does not resolve.

Life of a piece:  idea -> draft -> review -> approved -> scheduled -> published  (or dropped).
`approved`, `scheduled` and `published` are the person's decisions: the command line asks for a
typed confirmation, and nothing in Sourcebound posts by itself.
"""
from __future__ import annotations

import re
import shutil
from datetime import date, datetime
from pathlib import Path

import yaml

from . import config, results

STATUS = ["idea", "draft", "review", "approved", "scheduled", "published", "dropped"]
USER_ONLY = {"approved", "scheduled", "published"}      # set by the person, never by an agent
FIELDS = ("title", "kind", "template", "design", "status", "lang", "channel", "scheduled_at", "published_at", "url", "note", "prompt", "self_citation")
ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
HEADER = "# A piece: one small output of this project (`sb piece`). The text is in text.md.\n"


def folder(project: config.Project, piece_id: str) -> Path:
    if not ID.fullmatch(piece_id):
        raise ValueError("piece id: lowercase letters, digits, - and _")
    return project.root / "pieces" / piece_id


def get(piece_id: str, project: config.Project | None = None) -> dict:
    p = project or config.project()
    f = folder(p, piece_id) / "piece.yaml"
    if not f.exists():
        raise KeyError(f"no piece {piece_id}")
    return {"id": piece_id, **(yaml.safe_load(f.read_text(encoding="utf-8")) or {})}


def load(project: config.Project | None = None) -> list[dict]:
    p = project or config.project()
    out = []
    for f in sorted((p.root / "pieces").glob("*/piece.yaml")):
        try:
            out.append({"id": f.parent.name, **(yaml.safe_load(f.read_text(encoding="utf-8")) or {})})
        except yaml.YAMLError as e:
            out.append({"id": f.parent.name, "title": f.parent.name, "status": "draft", "error": str(e)})
    return out


def _clean(fields: dict) -> dict:
    out = {k: (str(v).strip() if v is not None else "") for k, v in fields.items() if k in FIELDS and v is not None}
    if "status" in out and out["status"] not in STATUS:
        raise ValueError(f"status must be one of {', '.join(STATUS)}")
    if "title" in out and not out["title"]:
        raise ValueError("a piece needs a title")
    for k in ("scheduled_at", "published_at"):
        if out.get(k):
            out[k] = _when(out[k])
    return out


def _when(text: str) -> str:
    """A date and time as ISO 8601 with offset; a time without offset is local time."""
    try:
        d = datetime.fromisoformat(text.strip().replace(" ", "T"))
    except ValueError:
        raise ValueError(f"not a date and time: {text!r} (use 2026-11-20 08:30)")
    return (d if d.tzinfo else d.astimezone()).isoformat(timespec="minutes")


def _save(project: config.Project, piece_id: str, meta: dict) -> None:
    f = folder(project, piece_id) / "piece.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    body = {k: v for k, v in meta.items() if k != "id" and v not in ("", None)}
    config.write_atomic(f, HEADER + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100))


def _slug(title: str, taken: set[str], width: int = 28) -> str:
    """Date and the title's first words, cut at a word boundary (about `width` characters)."""
    words = re.sub(r"[^a-z0-9]+", "-", title.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")).strip("-").split("-")
    base = words[0][:width]
    for w in words[1:]:
        if len(base) + 1 + len(w) > width:
            break
        base += "-" + w
    base = f"{date.today():%Y%m%d}-{base or 'piece'}"
    out, n = base, 1
    while out in taken:
        n += 1
        out = f"{base}-{n}"
    return out


def add(project: config.Project | None = None, *, piece_id: str | None = None, text: str | None = None, **fields) -> dict:
    """A new piece; returns its card. Without an id one is made from the date and the title."""
    p = project or config.project()
    new = _clean(fields)
    if not new.get("title"):
        raise ValueError("a piece needs a title")
    if new.get("status") in USER_ONLY:
        raise ValueError(f"a new piece starts as idea or draft; `{new['status']}` is set later, by the person")
    (p.root / "pieces").mkdir(exist_ok=True)
    with config.locked(p.root / "pieces" / ".ids"):
        pid = piece_id or _slug(new["title"], {x["id"] for x in load(p)})
        if (folder(p, pid) / "piece.yaml").exists():
            raise ValueError(f"piece {pid} exists")
        today = date.today().isoformat()
        meta = {"title": new["title"], "kind": new.get("kind") or "post", "template": new.get("template", ""),
                "design": new.get("design", ""), "status": new.get("status") or "idea", "lang": new.get("lang") or p.lang,
                "channel": new.get("channel") or _one_channel(p), "note": new.get("note", ""), "prompt": new.get("prompt", ""),
                "created": today, "updated": today}
        _save(p, pid, meta)
        tf = folder(p, pid) / "text.md"
        if not tf.exists():
            tf.write_text(text if text is not None else "", encoding="utf-8")
    return get(pid, p)


def _one_channel(project: config.Project) -> str:
    """The desk's channel when `project.yaml` names exactly one, else ''."""
    ch = project.meta.get("channels") or []
    ch = [ch] if isinstance(ch, str) else ch
    return str(ch[0]) if len(ch) == 1 else ""


def update(piece_id: str, project: config.Project | None = None, *, text: str | None = None, **fields) -> tuple[dict, dict]:
    """Change the card and/or the text; returns (before, after), each with its `text`."""
    p = project or config.project()
    new = _clean(fields)
    f = folder(p, piece_id)
    with config.locked(f / "piece.yaml"):
        before = {**get(piece_id, p), "text": read_text(piece_id, p)}
        meta = {**{k: v for k, v in before.items() if k != "text"}, **new, "updated": date.today().isoformat()}
        if new.get("status") == "scheduled" and not meta.get("scheduled_at"):
            raise ValueError("a scheduled piece needs a date and time (scheduled_at)")
        if "scheduled_at" in new and new["scheduled_at"] == "" and meta.get("status") == "scheduled":
            meta["status"] = "approved"
        _save(p, piece_id, meta)
        if text is not None:
            config.write_atomic(f / "text.md", text)
    return before, {**get(piece_id, p), "text": read_text(piece_id, p)}


def read_text(piece_id: str, project: config.Project | None = None) -> str:
    f = folder(project or config.project(), piece_id) / "text.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def remove(piece_id: str, project: config.Project | None = None) -> dict:
    """Move a piece to pieces/.removed/ (so a removal can be undone); returns its card and text."""
    p = project or config.project()
    card = {**get(piece_id, p), "text": read_text(piece_id, p)}
    bin_ = p.root / "pieces" / ".removed"
    bin_.mkdir(exist_ok=True)
    dest = bin_ / piece_id
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(folder(p, piece_id)), dest)
    return card


def restore(piece_id: str, project: config.Project | None = None) -> dict:
    p = project or config.project()
    src = p.root / "pieces" / ".removed" / piece_id
    if not src.exists():
        raise KeyError(f"no removed piece {piece_id}")
    if folder(p, piece_id).exists():
        raise ValueError(f"piece {piece_id} exists")
    shutil.move(str(src), folder(p, piece_id))
    return get(piece_id, p)


def due(project: config.Project | None = None, *, now: datetime | None = None) -> list[dict]:
    """Scheduled pieces whose time has come, oldest first."""
    now = now or datetime.now().astimezone()
    rows = [x for x in load(project) if x.get("status") == "scheduled" and x.get("scheduled_at")
            and datetime.fromisoformat(str(x["scheduled_at"])) <= now]
    return sorted(rows, key=lambda x: str(x["scheduled_at"]))


# ------------------------------------------------------------------ numbers typed by hand
# A number in a piece is a recorded result ({{result:key}}) or a quoted one, with its source
# cited in the same sentence.  Counted as a number: a decimal, a percentage, an integer with a
# thousands separator, any number with a currency, unit or scale (€, Mio., bn, x), and a bare
# integer of three or more digits.  Not counted: years, dates and times, paragraph and page
# numbers (§ 34f, Art. 6, S. 3), ids, hashtags, file names, and the conventional levels
# 1, 5, 10, 90, 95 and 99 per cent.
_UNIT = (r"%|Prozentpunkte?|Prozent|per\s?cent|percent|pp|bp|bps|Basispunkte?|€|\$|£|EUR|USD|GBP|CHF|Euro|Dollar"
         r"|Mio\.?|Mrd\.?|Bio\.?|Tsd\.?|Millionen|Million|Milliarden|Milliarde|millions?|billions?|thousand|trillion"
         r"|bn|mn|tn|k|m|km|kg|t|[kMGT]Wh|[kMG]W|x|×|-?fache[nmr]?|-?fach|-mal")
_NUMBER_IN_PIECE = re.compile(
    r"(?<![\w.,])(?P<pre>(?:[€$£]|EUR|USD|GBP|CHF)\s?)?"
    r"(?P<num>\d{1,3}(?:[.,  ]\d{3})+(?:[.,]\d+)?|\d+[.,]\d+|\d+)"
    rf"(?P<unit>\s?(?:{_UNIT}))?(?![\w])", re.IGNORECASE)
_PERCENT = re.compile(r"\s?(?:%|prozent|per\s?cent|percent)", re.IGNORECASE)
_NOT_A_NUMBER = re.compile("|".join([
    r"\{\{[^}]*\}\}",                                       # {{result:key}}, {{table:...}}
    r"\[[^\]]*@[^\]]*\]", r"(?<![\w@])@[A-Za-z][\w:.-]*\w",  # citations, with their page numbers
    r"\]\([^)]*\)", r"<[^>]*>", r"`[^`]*`", r"https?://\S+",  # link targets, tags, code, URLs
    r"(?<!\w)#\w+",                                          # hashtags
    r"\b[\w-]+\.(?:png|jpe?g|svg|gif|webp|pdf|csv|xlsx?|docx?|pptx?|ya?ml|json|md|html?)\b",
    r"\b[A-Z]{1,4}-\d+\b",                                   # ids such as W-0001
    r"§§?\s*\d+[a-z]*(?:\s*(?:Abs\.|Satz|Nr\.|S\.)\s*\d+[a-z]*)*",
    r"\b(?:Art|Abs|Nr|Rn|Rz|Ziff|Kap|Abb|Tab|Fig|No|Vol|Bd|Anh|Anl|S|p|pp|KW|Q|H)\.?\s?\d+[a-z]?\b",
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b",  # ISO dates and times
    r"(?<![\d.,])\d{1,2}\.\s?\d{1,2}\.\s?(?:\d{4}|\d{2})(?!\d|[.,]\d)",  # 01.10.2026
    r"(?<![\d.,])\d{1,2}/\d{1,2}/\d{2,4}(?!\d|[.,]\d)",
    r"(?<![\d.,/])(?:0?[1-9]|1[0-2])[./](?:19|20)\d{2}(?!\d|[.,]\d)",  # 09.2025, 9/2025
    r"(?<![\d.,])\d{1,2}:\d{2}(?!\d|[.,]\d)",                   # 08:30
]))
_LEVELS = {"1", "5", "10", "90", "95", "99"}
_ABBREV = {"mio", "mrd", "bio", "tsd", "ca", "rd", "bzw", "vgl", "ggf", "inkl", "zzgl", "nr", "abs", "art", "ff",
           "dr", "prof", "st", "jh", "mill", "etc", "vs", "approx", "no", "pp", "fig", "abb", "tab", "kap", "ziff",
           "bd", "hrsg", "mr", "ms", "mrs", "jan", "feb", "mar", "apr", "aug", "sep", "sept", "okt", "oct", "nov", "dez", "dec",
           "e.g", "i.e", "z.b", "u.a", "d.h", "o.ä", "u.ä", "s.o", "s.u"}
_BLOCK = re.compile(r"\n[ \t]*\n|\n(?=[ \t]*(?:[-*+][ \t]|\d+\.[ \t]|#|\|))")


def _masked(text: str) -> str:
    return _NOT_A_NUMBER.sub(lambda m: " " * len(m.group()), text)


def _sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence; a list item, a heading and a paragraph end one too."""
    out, start = [], 0
    for block in [*_BLOCK.finditer(text), None]:
        stop = block.start() if block else len(text)
        a = start
        for m in re.finditer(r"[.!?][\"”’)]*\s+(?!\[@)", text[start:stop]):
            end = start + m.start()
            word = re.search(r"([\w.]*)$", text[a:end]).group(1).lower()
            after = text[start + m.end(): start + m.end() + 1]
            if (word in _ABBREV or len(word) == 1 or re.fullmatch(r"\d{1,2}", word)
                    or (after and after.islower())):
                continue
            out.append((a, end + 1))
            a = start + m.end()
        out.append((a, stop))
        start = block.end() if block else stop
    return out


def typed_numbers(text: str) -> list[dict]:
    """Numbers written into a piece's text by hand: [{line, number, cited}], `cited` when the
    sentence holding the number cites a source ([@W-0001], @key)."""
    from .handover import MD_CITE
    masked, out = _masked(text), []
    spans = _sentences(text)
    for m in _NUMBER_IN_PIECE.finditer(masked):
        num, unit = m.group("num"), m.group("unit") or ""
        if m.group("pre") or unit:
            if _PERCENT.fullmatch(unit) and num in _LEVELS:
                continue
        elif not re.search(r"\d[.,  ]\d", num):        # a bare integer
            if len(num) < 3 or num.startswith("0") or (len(num) == 4 and 1900 <= int(num) <= 2099):
                continue
        a, b = next(((a, b) for a, b in spans if a <= m.start() < max(b, a + 1)), (0, len(text)))
        out.append({"line": text.count("\n", 0, m.start()) + 1, "number": m.group().strip(),
                    "cited": bool(MD_CITE.search(text[a:b]))})
    return out


_SKIP_KEYS = {"type", "layout", "prefix", "lang", "id", "image", "art", "file", "src", "logo", "template", "design",
              "url", "href", "date", "at"}


def _strings(node, path: str = "", cited: bool = False):
    """(path, text, cited) for every string in a data file; a mapping with a `source` that cites
    something counts as cited for everything inside it (a slide and its source line)."""
    from .handover import MD_CITE
    if isinstance(node, dict):
        cited = cited or any(MD_CITE.search(str(node.get(k) or "")) for k in ("source", "sources"))
        for k, v in node.items():
            if str(k) not in _SKIP_KEYS and k not in ("source", "sources"):
                yield from _strings(v, f"{path}.{k}" if path else str(k), cited)
    elif isinstance(node, list):
        for i, v in enumerate(node, 1):
            yield from _strings(v, f"{path}[{i}]", cited)
    elif isinstance(node, str):
        yield path, node, cited


def _lines(hits: list[dict], limit: int = 8) -> str:
    by: dict[int, list[str]] = {}
    for h in hits:
        by.setdefault(h["line"], []).append(h["number"])
    rows = [f"{n} ({', '.join(v)})" for n, v in sorted(by.items())]
    return ", ".join(rows[:limit]) + (f", and {len(rows) - limit} more" if len(rows) > limit else "")


def findings(piece_id: str, project: config.Project | None = None) -> dict:
    """{errors, warnings, info}: sources and results the piece refers to, numbers typed by hand
    (with or without a citation in the same sentence), the sources a recorded result rests on,
    stale renders."""
    import json

    from . import render
    p = project or config.project()
    doc = render.from_piece(p, piece_id)
    errs, warns, info = [], [], []
    body = doc.text + "\n" + json.dumps(doc.data, ensure_ascii=False)
    used = sorted({k.strip() for k in render.MD_RESULT.findall(body)})
    for k in sorted(set(used) - set(doc.results)):
        errs.append(f"result {k} is used but not recorded")
    own = [str(x).strip().lower() for x in ((p.meta.get("own") or {}).get("publishers") or []) if str(x).strip()]
    allowed = str(doc.meta.get("self_citation", p.meta.get("self_citation", True))).lower() in {"true", "yes", "1"}
    for k in render.cited(body):
        if re.fullmatch(r"W-\d{4}", k):
            if k not in doc.web_sources:
                errs.append(f"source {k} is cited but not in evidence/sources.yaml (sb snap URL, or sb doc FILE)")
            elif own and not allowed:
                who = str(doc.web_sources[k].get("publisher") or doc.web_sources[k].get("author") or "")
                if any(o in who.lower() for o in own):
                    errs.append(f"source {k} is the desk's own work ({who}): cite the original sources it rests on; "
                                "self_citation: true in the piece's card only where the person asked for it")
        elif k not in doc.references:
            warns.append(f"citation key {k} is not in evidence/inbox.bib or a references.bib of this project")
    if not render.cited(body) and doc.text.strip():
        warns.append("the text cites no source: every substantive statement needs one ([@W-0001] or [@citekey])")
    hits = typed_numbers(doc.text)
    bare = [h for h in hits if not h["cited"]]
    if bare:
        warns.append(f"text.md: numbers typed by hand with no citation in the same sentence, lines {_lines(bare)}: "
                     "record it and use {{result:key}}, or cite its source in that sentence")
    if len(bare) < len(hits):
        info.append(f"text.md: numbers quoted with a citation in the same sentence, lines {_lines([h for h in hits if h['cited']])}: "
                    "confirm each against the source")
    for stem, data in doc.data.items():
        cited, bare = [], []
        for path, text, ctx in _strings(data):
            for h in typed_numbers(text):
                (cited if h["cited"] or ctx else bare).append(f"{path} “{h['number']}”")
        short = lambda xs: ", ".join(xs[:8]) + (f", and {len(xs) - 8} more" if len(xs) > 8 else "")
        if bare:
            warns.append(f"{stem}.yaml: numbers typed by hand with no citation (positions count from 1): {short(bare)}: "
                         "use {{result:key}}, or cite the source in the text or in the slide's `source`")
        if cited:
            info.append(f"{stem}.yaml: numbers quoted under a citation: {short(cited)}: confirm each against the source")
    title = lambda s: (doc.web_sources.get(s) or {}).get("title")
    rest: dict[str, list[str]] = {}                 # what the results rest on -> the keys
    for k in (k for k in used if k in doc.results):
        prov = doc.results[k].get("provenance") or {}
        on = [f"{s} ({title(s)})" if title(s) else s for s in prov.get("sources") or []]
        on += [f"lake table {t}@{snap}" for t, snap in (prov.get("data") or {}).items()]
        rest.setdefault(", ".join(on), []).append(k)
    for on, keys in rest.items():
        what = f"result {keys[0]}" if len(keys) == 1 else f"results {', '.join(keys)}"
        info.append(f"{what} {'rests' if len(keys) == 1 else 'rest'} on {on}" if on else
                    f"{what} {'names' if len(keys) == 1 else 'name'} no source and no lake table "
                    "(results.record(..., sources=[\"W-0001\"]) says which source the inputs come from)")
    current = results.load(p)
    for m in render.renders(folder(p, piece_id) / "render"):
        changed = render.stale(m, current)
        if changed:
            warns.append(f"render {m['template']} shows older values of {', '.join(changed[:5])}: sb render {piece_id} --template {m['template']}")
    return {"errors": errs, "warnings": warns, "info": info}


def check(piece_id: str, project: config.Project | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) of `findings`."""
    f = findings(piece_id, project)
    return f["errors"], f["warnings"]


# ------------------------------------------------------------------ data files: structured content a template reads
DATA_NAME = re.compile(r"[a-z][a-z0-9_-]{0,40}")


def read_data(piece_id: str, name: str, project: config.Project | None = None) -> str | None:
    p = project or config.project()
    f = folder(p, piece_id) / f"{_data_name(name)}.yaml"
    return f.read_text(encoding="utf-8") if f.exists() else None


def _data_name(name: str) -> str:
    name = name.removesuffix(".yaml")
    if not DATA_NAME.fullmatch(name) or name == "piece":
        raise ValueError(f"data file name {name!r}: lowercase letters, digits, - and _ (e.g. slides); piece.yaml is the card")
    return name


def write_data(piece_id: str, name: str, text: str | None, project: config.Project | None = None) -> str | None:
    """Write `pieces/<id>/<name>.yaml` (structured content a template reads, e.g. slides.yaml), or remove it
    with None. The text must be YAML holding a mapping. Returns what was there before (None: nothing), so
    the change can be undone."""
    p = project or config.project()
    get(piece_id, p)
    f = folder(p, piece_id) / f"{_data_name(name)}.yaml"
    before = f.read_text(encoding="utf-8") if f.exists() else None
    if text is None:
        if f.exists():
            f.unlink()
        return before
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"{f.name} is not valid YAML: {e}")
    if not isinstance(data, dict):
        raise ValueError(f"{f.name} must hold a mapping (e.g. deck: and slides: for a slides template)")
    config.write_atomic(f, text if text.endswith("\n") else text + "\n")
    return before


# ------------------------------------------------------------------ focus: the piece the web view should show
def focus_path() -> Path | None:
    h = config.hub(required=False)
    return h.lake_root / "activity" / "focus.json" if h else None


def focus(piece_id: str, project: config.Project | None = None, *, why: str = "open") -> dict:
    """Ask the web view to show this piece (`sb piece open`; every render of a piece does it too).
    The view reads <data root>/activity/focus.json; nothing else changes."""
    import json
    p = project or config.project()
    get(piece_id, p)                                 # the piece exists
    stamp = {"project": p.slug, "piece": piece_id, "why": why, "at": datetime.now().astimezone().isoformat(timespec="seconds")}
    f = focus_path()
    if f is not None:
        f.parent.mkdir(parents=True, exist_ok=True)
        config.write_atomic(f, json.dumps(stamp, ensure_ascii=False) + "\n")
    return stamp


def current_focus() -> dict | None:
    import json
    f = focus_path()
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f and f.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


# ------------------------------------------------------------------ export: a piece's files, where the person keeps them
MARKER = ".sourcebound-export.json"


def export_name(piece_id: str, meta: dict, pattern: str = "{date}_{slug}") -> str:
    """The folder name of an export: `{date}` is the planned posting day (else today) as YYYYMMDD,
    `{slug}` the piece id without its date prefix, `{id}` the id."""
    at = str(meta.get("scheduled_at") or "")[:10]
    day = at.replace("-", "") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", at) else f"{date.today():%Y%m%d}"
    slug = re.sub(r"^\d{8}-", "", piece_id).replace("-", "_")
    name = pattern.format(date=day, slug=slug, id=piece_id)
    if not name or name in (".", "..") or re.search(r"[\\/:*?\"<>|]", name):
        raise ValueError(f"export name {name!r} from {pattern!r} is not a folder name")
    return name


def prepare_export(dest: Path, piece_id: str) -> None:
    """Make `dest` ready for an export of this piece without ever deleting what someone else put there:
    a new folder, or one that an earlier export of the same piece wrote (its marker lists the files)."""
    import json
    if dest.exists() and not dest.is_dir():
        raise ValueError(f"{dest} is a file")
    if dest.is_dir() and any(dest.iterdir()):
        marker = dest / MARKER
        old = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else None
        if not old or old.get("piece") != piece_id:
            raise ValueError(f"{dest} exists and was not written by an export of {piece_id}; choose another folder "
                             "or move it away (nothing was changed)")
        for name in old.get("files", []):                 # only what the last export wrote
            f = dest / name
            if f.is_file() and f.parent == dest:
                f.unlink()
    dest.mkdir(parents=True, exist_ok=True)


def export(piece_id: str, project: config.Project | None = None, *, to: str | Path | None = None) -> dict:
    """Copy what a piece is made of to the folder where it is kept (for a LinkedIn desk e.g.
    U:/Marketing/LinkedIn/20261120_slug): the newest render of every template, the post text and the
    alternative texts. Where: `to`, else `export.dir` in project.yaml, in a folder named after
    `export.name` (default "{date}_{slug}"). Nothing is posted; the export is a copy."""
    import json
    from . import render
    p = project or config.project()
    meta = get(piece_id, p)
    conf = p.meta.get("export") if isinstance(p.meta.get("export"), dict) else {}
    root = Path(str(to or conf.get("dir") or "")).expanduser() if (to or conf.get("dir")) else None
    if root is None:
        raise ValueError("no export folder: give one (sb piece export ID --to FOLDER) or set export.dir in project.yaml")
    if not root.is_absolute():
        root = (p.root / root).resolve()
    if not root.is_dir():
        raise ValueError(f"the export folder {root} does not exist (is the drive connected?)")
    dest = root / export_name(piece_id, meta, str(conf.get("name") or "{date}_{slug}"))
    newest: dict[str, dict] = {}
    for m in render.renders(folder(p, piece_id) / "render"):
        if m["template"] not in newest or m["at"] > newest[m["template"]]["at"]:
            newest[m["template"]] = m
    if not newest:
        raise ValueError(f"{piece_id} has no render yet: sb render {piece_id} --template ID")
    prepare_export(dest, piece_id)
    written: list[str] = []
    for m in newest.values():
        src = Path(m["folder"])
        for name in m.get("files") or []:
            f = src / name
            if f.is_file() and f.suffix.lower() not in {".json", ".html"} and name not in written:
                shutil.copy2(f, dest / Path(name).name)
                written.append(Path(name).name)
        pv = src / "preview.json"
        if pv.exists() and "post.txt" not in written:
            view = json.loads(pv.read_text(encoding="utf-8"))
            (dest / "post.txt").write_text(view.get("text", ""), encoding="utf-8")
            alts = [f"{s['file']}\n{s['alt']}" for s in view.get("slides", []) if s.get("file") and s.get("alt")]
            written.append("post.txt")
            if alts:
                (dest / "alt-texts.txt").write_text("\n\n".join(alts) + "\n", encoding="utf-8")
                written.append("alt-texts.txt")
    stamp = {"piece": piece_id, "project": p.slug, "at": datetime.now().astimezone().isoformat(timespec="seconds"),
             "renders": {t: m["at"] for t, m in newest.items()}, "files": written}
    (dest / MARKER).write_text(json.dumps(stamp, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"folder": str(dest), "files": written, "renders": sorted(newest)}


def summary(project: config.Project | None = None) -> list[dict]:
    """Every piece with its text, renders and files, for the frontend."""
    from . import render
    p = project or config.project()
    out = []
    for card in load(p):
        f = folder(p, card["id"])
        rs = []
        for m in render.renders(f / "render"):
            rel = Path(m["folder"]).relative_to(p.root).as_posix()
            rs.append({"template": m["template"], "kind": m["kind"], "design": m["design"], "at": m["at"], "notes": m.get("notes") or [],
                       "files": [f"{rel}/{x}" for x in m["files"]], "stale": render.stale(m, results.load(p))})
        out.append({**card, "text": read_text(card["id"], p),
                    "data_files": sorted(x.name for x in f.glob("*.yaml") if x.name != "piece.yaml"), "renders": rs})
    return out
