"""Plugins: optional packages that add output formats and commands to Sourcebound.

The core renders LaTeX and writes the format-neutral handover.  Everything else (Word,
slides and posts, later video) is a plugin: its own Python package with its own
dependencies, installed only by those who want it.

A plugin is a package that declares an entry point in the group `sourcebound.plugins`:

    [project.entry-points."sourcebound.plugins"]
    word = "sourcebound_word:register"

and a function `register(api)` that says what it brings:

    def register(api):
        api.renderer("docx", render, title="Word document from a .docx template")
        api.command("word", setup_parser, run)           # adds `sb word ...`
        api.check("docx", check)                         # optional: checks before rendering
        api.pack(Path(__file__).parent / "pack")         # optional: designs/ and templates/ it brings
        api.converter(".docx", ".pdf", to_pdf)           # optional: a format conversion for `sb deliver`
        api.chart_renderer("firm", draw)                 # optional: charts in an organisation's style (see charts.py)

A plugin that is not installed into the environment (a private one, kept in a shared folder) is
named in the user configuration instead; `sb plugin add FOLDER` writes it there:

    [plugins]
    paths = ["W:/Example/sourcebound-plugins/firm-plugin"]

Such a folder holds the package as it would be installed (pyproject.toml with the entry point,
the code in src/ or beside it). It is loaded from there, so `uv sync` and `sb update`, which
remove what the environment does not list, leave it alone. Its dependencies must be installed.

A renderer turns one `Document` (see `render.py`) into files, using a registered template
and a design.  Plugins never reach around the core: they read a project through
`sourcebound.config`, `ledger`, `results` and `render`, and write only below the output
folder they are given.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Callable

GROUP = "sourcebound.plugins"
PATH_ENV = "SB_PLUGIN_PATH"         # further plugin folders, separated like PATH


@dataclass
class Renderer:
    kind: str                       # the template kind it renders, e.g. "docx", "slides"
    fn: Callable                    # render(doc, template, design, out) -> list[Path], or (list[Path], notes)
    title: str = ""
    plugin: str = ""
    outputs: tuple = ()             # file suffixes it writes, for listings
    data: tuple = ()                # data files of a piece it reads, e.g. ("slides",) for pieces/<id>/slides.yaml
    guide: str = ""                 # Markdown: the format of those files, for people and agents (`sb template guide`)


@dataclass
class Converter:
    source: str                     # file suffix it reads, e.g. ".docx"
    target: str                     # file suffix it writes, e.g. ".pdf"
    fn: Callable                    # convert(path, out) -> Path, or (Path, notes)
    title: str = ""
    plugin: str = ""


@dataclass
class ChartRenderer:
    name: str                       # what a design names in `charts: {renderer: NAME}`
    fn: Callable                    # render(block, *, design, width_px, height_px, out, lang, text_px, scale) -> Path
    types: tuple = ()               # block types it draws (empty: the same as the built-in renderer)
    title: str = ""
    plugin: str = ""


@dataclass
class Plugin:
    name: str
    version: str = ""
    package: str = ""
    error: str | None = None
    renderers: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    packs: list[str] = field(default_factory=list)
    converters: list[str] = field(default_factory=list)
    chart_renderers: list[str] = field(default_factory=list)


class Api:
    """What `register(api)` of a plugin may call."""

    def __init__(self, plugin: Plugin, registry: "Registry"):
        self._plugin, self._registry = plugin, registry

    def renderer(self, kind: str, fn: Callable, *, title: str = "", outputs: tuple = (), data: tuple = (), guide: str = "") -> None:
        """`data`: the files of a piece this renderer reads (`slides` for slides.yaml); `guide`: their format,
        as Markdown, so an agent can write them without guessing."""
        self._registry.renderers[kind] = Renderer(kind, fn, title, self._plugin.name, tuple(outputs), tuple(data), guide)
        self._plugin.renderers.append(kind)

    def command(self, name: str, setup: Callable, run: Callable, *, help: str = "") -> None:
        """`setup(parser)` adds arguments to an argparse parser; `run(args)` does the work."""
        self._registry.commands[name] = (setup, run, help, self._plugin.name)
        self._plugin.commands.append(name)

    def check(self, kind: str, fn: Callable) -> None:
        """`fn(doc, template, design) -> list[str]`: problems that must stop a render."""
        self._registry.checks.setdefault(kind, []).append(fn)

    def pack(self, folder) -> None:
        """A folder with `designs/` and `templates/` that this plugin brings along.

        This is how an organisation ships its look as an installable package: the designs and
        templates are found without `sb pack install`.  The registry of the data root still wins,
        so a machine can override one of them.
        """
        from pathlib import Path
        self._registry.packs.append(Path(folder))
        self._plugin.packs.append(str(folder))

    def scaffold(self, kind: str, fn: Callable) -> None:
        """`fn(folder, design) -> None`: writes a starting template of this kind into a new folder."""
        self._registry.scaffolds[kind] = fn

    def converter(self, source: str, target: str, fn: Callable, *, title: str = "") -> None:
        """`fn(path, out) -> Path` or `(Path, notes)`: one file turned into another format (e.g. .docx -> .pdf).

        `sb deliver` uses converters to add formats to what was rendered."""
        key = (source.lower(), target.lower())
        self._registry.converters[key] = Converter(key[0], key[1], fn, title, self._plugin.name)
        self._plugin.converters.append(f"{key[0]} -> {key[1]}")

    def chart_renderer(self, name: str, fn: Callable, *, types: tuple = (), title: str = "") -> None:
        """`fn(block, *, design, width_px, height_px, out, lang, text_px=None, scale=2.0) -> Path`: draws one
        chart block of a deck as an image, in an organisation's chart style.

        A design selects it by name (`charts: {renderer: NAME}` in design.yaml); `sourcebound.charts`
        falls back to its own renderer, with a note, when no installed plugin has that name."""
        self._registry.chart_renderers[name] = ChartRenderer(name, fn, tuple(types), title, self._plugin.name)
        self._plugin.chart_renderers.append(name)


@dataclass
class Registry:
    plugins: list[Plugin] = field(default_factory=list)
    renderers: dict[str, Renderer] = field(default_factory=dict)
    commands: dict[str, tuple] = field(default_factory=dict)
    checks: dict[str, list[Callable]] = field(default_factory=dict)
    scaffolds: dict[str, Callable] = field(default_factory=dict)
    packs: list = field(default_factory=list)
    converters: dict[tuple, Converter] = field(default_factory=dict)
    chart_renderers: dict[str, ChartRenderer] = field(default_factory=dict)


_REGISTRY: Registry | None = None


def load(*, fresh: bool = False) -> Registry:
    """Every installed plugin, registered.  A plugin that fails to load is listed with its error."""
    global _REGISTRY
    if _REGISTRY is not None and not fresh:
        return _REGISTRY
    reg = Registry()
    from . import render
    render.register_builtin(Api(Plugin("sourcebound"), reg))
    for ep in sorted(metadata.entry_points(group=GROUP), key=lambda e: e.name):
        dist = getattr(ep, "dist", None)
        p = Plugin(ep.name, version=dist.version if dist else "", package=dist.name if dist else "")
        try:
            ep.load()(Api(p, reg))
        except Exception as e:                      # one broken plugin must not take `sb` down
            p.error = f"{type(e).__name__}: {e}"
        reg.plugins.append(p)
    installed = {p.name for p in reg.plugins}
    for folder in folders():
        try:
            entries, version, package, src = folder_entries(folder)
        except (OSError, ValueError) as e:
            reg.plugins.append(Plugin(folder.name, package=f"folder {folder}", error=str(e)))
            continue
        for name, target in entries.items():
            p = Plugin(name, version=version, package=f"{package} (folder {folder})")
            if name in installed:                   # the installed package wins; say so instead of loading twice
                p.error = f"also installed in the environment; the installed one is used"
                reg.plugins.append(p)
                continue
            try:
                import importlib
                import sys
                if str(src) not in sys.path:
                    sys.path.insert(0, str(src))
                module, _, attr = target.partition(":")
                getattr(importlib.import_module(module), attr or "register")(Api(p, reg))
            except Exception as e:
                p.error = f"{type(e).__name__}: {e}"
            reg.plugins.append(p)
    _REGISTRY = reg
    return reg


def folders() -> list:
    """Plugin folders of this machine: [plugins] paths in the user configuration, then SB_PLUGIN_PATH."""
    import os
    import tomllib
    from pathlib import Path
    from . import config
    out: list[Path] = []
    u = config.user_config_path()
    if u.exists():
        try:
            out += [Path(str(x)).expanduser() for x in (tomllib.loads(u.read_text(encoding="utf-8")).get("plugins") or {}).get("paths") or []]
        except tomllib.TOMLDecodeError:
            pass
    out += [Path(x).expanduser() for x in os.environ.get(PATH_ENV, "").split(os.pathsep) if x.strip()]
    seen, unique = set(), []
    for f in out:
        if str(f) not in seen:
            seen.add(str(f))
            unique.append(f)
    return unique


def folder_entries(folder) -> tuple[dict, str, str, object]:
    """({name: "module:function"}, version, package name, the folder to import from) of a plugin folder."""
    import tomllib
    from pathlib import Path
    folder = Path(folder)
    py = folder / "pyproject.toml"
    if not py.is_file():
        raise ValueError(f"{folder} is not a plugin folder (no pyproject.toml); is the drive connected?")
    doc = tomllib.loads(py.read_text(encoding="utf-8"))
    project = doc.get("project") or {}
    entries = ((project.get("entry-points") or {}).get(GROUP)) or {}
    if not entries:
        raise ValueError(f"{py} declares no entry point in [project.entry-points.\"{GROUP}\"]")
    src = folder / "src" if (folder / "src").is_dir() else folder
    return dict(entries), str(project.get("version") or ""), str(project.get("name") or folder.name), src


def add_folder(folder) -> list:
    """Name a plugin folder in the user configuration ([plugins] paths); returns the list."""
    return _set_folders(lambda now, f: now if f in now else [*now, f], folder, check=True)


def remove_folder(folder) -> list:
    return _set_folders(lambda now, f: [x for x in now if x != f], folder, check=False)


def _set_folders(change, folder, *, check: bool) -> list:
    import json
    import re
    import tomllib
    from pathlib import Path
    from . import config
    f = Path(folder).expanduser().absolute().as_posix()      # as typed: a mapped drive stays W:/..., not \\server\share
    if check:
        folder_entries(f)
    u = config.user_config_path()
    text = u.read_text(encoding="utf-8") if u.exists() else ""
    now = [str(x) for x in ((tomllib.loads(text).get("plugins") or {}).get("paths") or [])] if text else []
    new = change(now, f)
    line = "paths = " + json.dumps(new, ensure_ascii=False)
    if re.search(r"(?m)^\[plugins\]\s*$", text):
        section = re.search(r"(?ms)^\[plugins\]\s*$(.*?)(?=^\[|\Z)", text)
        body = section.group(1)
        body = re.sub(r"(?m)^paths\s*=.*$", lambda _m: line, body) if re.search(r"(?m)^paths\s*=", body) else "\n" + line + body
        text = text[:section.start(1)] + body + text[section.end(1):]
    else:
        head = "# Plugin folders loaded from where they are (sb plugin add FOLDER)\n[plugins]\n"
        text = text.rstrip("\n") + ("\n\n" if text else "") + head + line + "\n"
    u.parent.mkdir(parents=True, exist_ok=True)
    tomllib.loads(text)                             # never write a configuration that does not parse
    config.write_atomic(u, text)
    global _REGISTRY
    _REGISTRY = None
    return new


def listing() -> list[dict]:
    return [{"name": p.name, "package": p.package, "version": p.version, "error": p.error,
             "renderers": p.renderers, "commands": p.commands, "packs": p.packs, "converters": p.converters,
             "chart_renderers": p.chart_renderers}
            for p in load().plugins]
