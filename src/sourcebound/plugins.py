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


@dataclass
class Renderer:
    kind: str                       # the template kind it renders, e.g. "docx", "slides"
    fn: Callable                    # render(doc, template, design, out) -> list[Path], or (list[Path], notes)
    title: str = ""
    plugin: str = ""
    outputs: tuple = ()             # file suffixes it writes, for listings


@dataclass
class Converter:
    source: str                     # file suffix it reads, e.g. ".docx"
    target: str                     # file suffix it writes, e.g. ".pdf"
    fn: Callable                    # convert(path, out) -> Path, or (Path, notes)
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


class Api:
    """What `register(api)` of a plugin may call."""

    def __init__(self, plugin: Plugin, registry: "Registry"):
        self._plugin, self._registry = plugin, registry

    def renderer(self, kind: str, fn: Callable, *, title: str = "", outputs: tuple = ()) -> None:
        self._registry.renderers[kind] = Renderer(kind, fn, title, self._plugin.name, tuple(outputs))
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


@dataclass
class Registry:
    plugins: list[Plugin] = field(default_factory=list)
    renderers: dict[str, Renderer] = field(default_factory=dict)
    commands: dict[str, tuple] = field(default_factory=dict)
    checks: dict[str, list[Callable]] = field(default_factory=dict)
    scaffolds: dict[str, Callable] = field(default_factory=dict)
    packs: list = field(default_factory=list)
    converters: dict[tuple, Converter] = field(default_factory=dict)


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
    _REGISTRY = reg
    return reg


def listing() -> list[dict]:
    return [{"name": p.name, "package": p.package, "version": p.version, "error": p.error,
             "renderers": p.renderers, "commands": p.commands, "packs": p.packs, "converters": p.converters}
            for p in load().plugins]
