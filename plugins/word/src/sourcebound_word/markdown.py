"""The handover notation as blocks and spans (no dependency, no Word).

Blocks (dicts with `type`):
    heading   level, spans, label, md
    para      spans, md
    list      ordered, items [(depth, spans)], md
    quote     spans, md
    code      text, md
    math      text, md
    table     name | rows, caption (spans), label, note (spans), md
    figure    file, caption (spans), label, md

Spans (dicts with `t`):
    text      s, b, i, code, href
    result    key
    cite      keys, locator, textual
    ref       label
    math      s
    br
`md` is the block's own Markdown, kept so that an unchanged block can be written back as it was.
"""
from __future__ import annotations

import re

_INLINE = re.compile(
    r"(?P<code>`[^`\n]*`)"
    r"|(?P<math>(?<![\\$])\$(?!\s)[^$\n]*?(?<![\\\s])\$)"
    r"|(?P<result>\{\{result:[^}]+\}\})"
    r"|(?P<ref>\{\{ref:[^}]+\}\})"
    r"|(?P<image>!\[[^\]]*\]\([^)]*\)(?:\{#[^}]*\})?)"
    r"|(?P<link>\[(?P<ltext>[^\[\]]+)\]\((?P<lurl>[^)\s]+)\))"
    r"|(?P<group>\[(?P<gbody>[^\[\]]*@[A-Za-z][^\[\]]*)\](?!\())"
    r"|(?P<auto><(?P<aurl>https?://[^>\s]+)>)"
    r"|(?P<bold>\*\*(?P<btext>.+?)\*\*)"
    r"|(?P<ital>(?<![\w*])\*(?P<itext>[^*\n]+)\*(?![\w*]))"
    r"|(?P<bare>(?<![\w@])@(?P<bkey>[A-Za-z][\w:.-]*\w))"
    r"|(?P<br> {2,}\n|\\\n)"
    r"|(?P<esc>\\(?P<echar>[\\`*_{}\[\]()#+\-.!|<>$]))",
    re.S,
)
_KEY = re.compile(r"^(.*?)@([A-Za-z][\w:.-]*\w)(.*)$", re.S)


def spans(text: str, *, known=None, b: bool = False, i: bool = False, href: str | None = None) -> list[dict]:
    """Inline text as spans. `known(key) -> bool` says whether a bare @key is a source (else it is text)."""
    out: list[dict] = []

    def plain(s: str) -> None:
        s = re.sub(r"[ \t]*\n[ \t]*", " ", s)
        if not s:
            return
        if out and out[-1]["t"] == "text" and (out[-1]["b"], out[-1]["i"], out[-1]["code"], out[-1]["href"]) == (b, i, False, href):
            out[-1]["s"] += s
        else:
            out.append({"t": "text", "s": s, "b": b, "i": i, "code": False, "href": href})
    pos = 0
    for m in _INLINE.finditer(text):
        plain(text[pos:m.start()])
        pos = m.end()
        kind = m.lastgroup if m.lastgroup in {"code", "math", "result", "ref", "image", "link", "group", "auto", "bold", "ital", "bare", "br", "esc"} else next(
            k for k in ("code", "math", "result", "ref", "image", "link", "group", "auto", "bold", "ital", "bare", "br", "esc") if m.group(k))
        if kind == "code":
            out.append({"t": "text", "s": m.group(0)[1:-1], "b": b, "i": i, "code": True, "href": href})
        elif kind == "math":
            out.append({"t": "math", "s": m.group(0)[1:-1]})
        elif kind == "result":
            out.append({"t": "result", "key": m.group(0)[9:-2].strip()})
        elif kind == "ref":
            out.append({"t": "ref", "label": m.group(0)[6:-2].strip()})
        elif kind == "image":
            pass                                    # an image inside a sentence: dropped (figures are blocks)
        elif kind == "link":
            out.extend(spans(m.group("ltext"), known=known, b=b, i=i, href=m.group("lurl")))
        elif kind == "auto":
            out.append({"t": "text", "s": m.group("aurl"), "b": b, "i": i, "code": False, "href": m.group("aurl")})
        elif kind == "group":
            items = [_KEY.match(x.strip()) for x in m.group("gbody").split(";")]
            if all(items):
                prefix = items[0].group(1).strip()
                if prefix:
                    plain(prefix + " ")
                out.append({"t": "cite", "keys": [x.group(2) for x in items], "locator": items[-1].group(3).strip(" ,"), "textual": False})
            else:
                plain(m.group(0))
        elif kind == "bold":
            out.extend(spans(m.group("btext"), known=known, b=True, i=i, href=href))
        elif kind == "ital":
            out.extend(spans(m.group("itext"), known=known, b=b, i=True, href=href))
        elif kind == "bare":
            if known is None or known(m.group("bkey")):
                out.append({"t": "cite", "keys": [m.group("bkey")], "locator": "", "textual": True})
            else:
                plain(m.group(0))
        elif kind == "br":
            out.append({"t": "br"})
        else:
            plain(m.group("echar"))
    plain(text[pos:])
    return out


def _paragraphs(text: str) -> list[str]:
    """Paragraphs of a Markdown text; a fenced code block stays one paragraph."""
    out, cur, fenced = [], [], False

    def flush():
        if any(x.strip() for x in cur):
            out.append("\n".join(cur).strip("\n"))
        cur.clear()
    for line in text.replace("\r\n", "\n").split("\n"):
        if re.match(r"\s*```", line):
            fenced = not fenced
        if not fenced and not line.strip():
            flush()
        else:
            cur.append(line)
    flush()
    return out


_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_HEAD = re.compile(r"^(#{1,6}) (.+?)(?:\s*\{#([^}]+)\})?\s*$")
_FIG = re.compile(r"^!\[([\s\S]*)\]\(([^)\s]+)\)(?:\{#([^}]+)\})?$")
_TABLE = re.compile(r"^\{\{table:([^}]+)\}\}$")
_NOTE = re.compile(r"^\*[^*][\s\S]*\*$")


def _is_pipe(p: str | None) -> bool:
    return bool(p and p.lstrip().startswith("|") and re.search(r"\n\s*\|[\s:|-]+\|", p))


def _pipe_rows(p: str) -> list[list[str]]:
    rows = []
    for n, line in enumerate(p.strip().split("\n")):
        if n == 1:
            continue                                # the rule under the header
        cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
        rows.append([c.strip().replace("\\|", "|") for c in cells])
    return rows


def blocks(text: str, *, known=None) -> list[dict]:
    paras, out, i = _paragraphs(text), [], 0
    sp = lambda s: spans(s, known=known)
    while i < len(paras):
        p = paras[i]
        head, fig, tab = _HEAD.match(p) if "\n" not in p else None, _FIG.match(p.strip()), _TABLE.match(p.strip())
        if head:
            out.append({"type": "heading", "level": min(len(head.group(1)), 3), "spans": sp(head.group(2).strip()),
                        "label": head.group(3), "md": p})
        elif fig:
            out.append({"type": "figure", "file": fig.group(2).split("/")[-1], "caption": sp(re.sub(r"\s+", " ", fig.group(1))),
                        "label": fig.group(3), "md": p})
        elif tab or p.startswith(": ") or _is_pipe(p):
            # a table is a CSV reference or a pipe table, with caption and note next to it in any order
            name, rows = (tab.group(1).strip() if tab else None), (_pipe_rows(p) if _is_pipe(p) else None)
            caption, note, md = (p if p.startswith(": ") else ""), "", [p]
            while i + 1 < len(paras):
                nxt = paras[i + 1]
                if not caption and nxt.startswith(": "):
                    caption = nxt
                elif not note and _NOTE.match(nxt) and "*" not in nxt[1:-1] and (caption or name or rows):
                    note = nxt[1:-1]
                elif not name and rows is None and _is_pipe(nxt):
                    rows = _pipe_rows(nxt)
                elif not name and rows is None and _TABLE.match(nxt.strip()):
                    name = _TABLE.match(nxt.strip()).group(1).strip()
                else:
                    break
                md.append(nxt)
                i += 1
            label = (re.search(r"\{#([^}]+)\}\s*$", caption) or [None, None])[1]
            cap = re.sub(r"\s+", " ", re.sub(r"\s*\{#[^}]+\}\s*$", "", caption[2:] if caption else ""))
            out.append({"type": "table", "name": name, "rows": rows, "caption": sp(cap), "label": label,
                        "note": sp(re.sub(r"\s+", " ", note)), "md": "\n\n".join(md)})
        elif p.lstrip().startswith("```"):
            body = p.strip().split("\n")
            out.append({"type": "code", "text": "\n".join(body[1:-1] if body[-1].strip().startswith("```") else body[1:]), "md": p})
        elif re.fullmatch(r"\$\$[\s\S]*\$\$", p.strip()):
            out.append({"type": "math", "text": p.strip()[2:-2].strip(), "md": p})
        elif _ITEM.match(p.split("\n")[0]):
            items: list[list] = []
            for line in p.split("\n"):
                m = _ITEM.match(line)
                if m:
                    items.append([min(len(m.group(1).expandtabs(4)) // 2, 2), m.group(3)])
                elif items:
                    items[-1][1] += " " + line.strip()
            out.append({"type": "list", "ordered": bool(re.match(r"\s*\d", p)), "items": [(d, sp(t)) for d, t in items], "md": p})
        elif all(line.lstrip().startswith(">") for line in p.split("\n")):
            out.append({"type": "quote", "spans": sp(" ".join(re.sub(r"^\s*>\s?", "", line) for line in p.split("\n"))), "md": p})
        else:
            out.append({"type": "para", "spans": sp(p), "md": p})
        i += 1
    return out


def cite_markdown(keys: list[str], locator: str, textual: bool) -> str:
    """A citation back in the notation."""
    if textual and len(keys) == 1:
        return f"@{keys[0]}" + (f" [{locator}]" if locator else "")
    return "[" + "; ".join(f"@{k}" for k in keys) + (f", {locator}" if locator else "") + "]"
