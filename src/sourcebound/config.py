"""Locate the configuration (hub.toml or the user configuration) and the current project (project.yaml)."""
from __future__ import annotations

import os
import time
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


def find_up(name: str, start: str | Path | None = None) -> Path | None:
    """First directory at or above `start` (default: cwd) that contains `name`."""
    d = Path(start or Path.cwd()).resolve()
    for p in (d, *d.parents):
        try:
            if (p / name).exists():
                return p
        except OSError:          # a folder above may not be readable (the root of a network share)
            continue
    return None


@contextmanager
def locked(path: Path, *, timeout: float = 600.0, stale: float = 120.0):
    """Exclusive use of `path` across processes (parallel agents write the same files).

    A `<name>.lock` file next to it, created atomically; one left behind by a process that
    died is taken over after `stale` seconds.
    """
    lock = Path(path).with_name(Path(path).name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                continue
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"{lock} is held by another process")
            time.sleep(0.05)
        except PermissionError:                     # Windows: the holder is just removing it
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def write_atomic(path: Path, text: str) -> None:
    """Write through a temporary file, so a reader never sees half a file."""
    tmp = Path(path).with_name(f"{Path(path).name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:                     # Windows: a reader has the file open
            if attempt == 49:
                raise
            time.sleep(0.05)


def _expand(s: str, root: str = "") -> str:
    return os.path.expanduser(s.replace("{root}", root))


def user_config_path() -> Path:
    """User-level configuration: $XDG_CONFIG_HOME/sourcebound/config.toml (default ~/.config)."""
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "sourcebound" / "config.toml"


def home() -> Path | None:
    """The Sourcebound checkout this package runs from (templates, latex, agents), if any."""
    p = Path(__file__).resolve().parents[2]
    return p if (p / "templates" / "project").exists() else None


def locate(start: str | Path | None = None) -> tuple[Path, str] | None:
    """Configuration file and where it came from: 'env' | 'hub' | 'user'.

    Order: SB_CONFIG -> nearest hub.toml at or above `start` -> user configuration.
    """
    env = os.environ.get("SB_CONFIG")
    if env:
        return Path(env).expanduser().resolve(), "env"
    root = find_up("hub.toml", start)
    if root is not None:
        return root / "hub.toml", "hub"
    u = user_config_path()
    return (u, "user") if u.exists() else None


@dataclass(frozen=True)
class Hub:
    root: Path              # folder relative paths resolve against: <hub>/ or the checkout
    lake_root: Path         # the data root
    catalog: str            # "sqlite:/abs/path" | "postgres:..." | "duckdb:/abs/path"
    data_path: str          # local dir (with trailing /) or s3://...
    raw_root: Path
    user_agent: str
    min_interval: float
    jitter: float
    respect_robots: bool
    zotero_url: str
    zotero_collection_root: str
    github_owner: str
    project_template: Path
    registry: Path = Path()             # <data root>/registry: shared contracts + source register
    config_file: Path | None = None
    source: str = "hub"                 # 'env' | 'hub' | 'user'
    lake_root_from: str = "config"      # 'SB_LAKE_ROOT' | 'project.yaml' | 'config'
    projects_dir: Path | None = None    # default parent folder for `sb new` outside a hub
    latex_templates: tuple = ()         # ((name, folder), ...) from [templates.latex]
    deliverable_template: str | None = None   # [templates] deliverable: default for `sb new`
    library: Path = Path()              # <data root>/library: PDFs of papers and their text
    converter: str | None = None        # [library] converter: optional PDF -> Markdown command

    @property
    def contract_bases(self) -> list[Path]:
        """Folders that hold `contracts/` for shared tables: the registry first, then the hub."""
        return [b for b in (self.registry, self.root) if (b / "contracts").is_dir()]

    @property
    def contracts_dir(self) -> Path:
        """Where a new shared contract belongs."""
        bases = self.contract_bases
        return (bases[0] if bases else self.root) / "contracts"

    @property
    def datasources_dir(self) -> Path:
        """Where a new source register entry belongs."""
        d = self.registry / "datasources"
        return d if d.is_dir() else self.root / "datasources"

    def datasource(self, source_id: str) -> Path | None:
        for base in (self.registry, self.root):
            f = base / "datasources" / f"{source_id}.yaml"
            if f.exists():
                return f
        return None


@lru_cache(maxsize=None)
def _load_hub(path: Path, source: str, data_root: str | None, env: tuple) -> Hub:
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    if source == "hub" and "root" not in cfg.get("lake", {}):
        # A hub.toml that names no data root (the checkout's own) follows the machine's choice:
        # the data root and the projects folder of the user configuration (`sb init`).
        u = user_config_path()
        if u.exists():
            user = tomllib.loads(u.read_text(encoding="utf-8"))
            cfg = {**cfg, "lake": {**user.get("lake", {}), **cfg.get("lake", {})},
                   "projects": {**user.get("projects", {}), **cfg.get("projects", {})}}
    lk, fe = cfg.get("lake", {}), cfg.get("fetch", {})
    env_root, env_catalog, env_data = env
    root = path.parent
    if source != "hub":
        own = cfg.get("sourcebound", {}).get("home")
        root = Path(_expand(own)).resolve() if own else (home() or path.parent)
    lake_root = _expand(env_root or data_root or lk.get("root", "~/research-lake"))
    if not Path(lake_root).is_absolute():
        lake_root = str((path.parent / lake_root).resolve())
    catalog = _expand(env_catalog or lk.get("catalog", "sqlite:{root}/catalog.sqlite"), lake_root)
    data_path = _expand(env_data or lk.get("data_path", "{root}/data/"), lake_root)
    if "://" not in data_path and not data_path.endswith("/"):
        data_path += "/"
    template = _hub_path(root, cfg.get("templates", {}).get("project", "templates/project"))
    if not template.exists() and home() is not None:
        template = home() / "templates" / "project"
    pdir = cfg.get("projects", {}).get("dir")
    return Hub(
        root=root,
        lake_root=Path(lake_root),
        catalog=catalog,
        data_path=data_path,
        raw_root=Path(_expand(lk.get("raw", "{root}/raw"), lake_root)),
        user_agent=fe.get("user_agent", "sourcebound/0.1 (research)"),
        min_interval=float(fe.get("min_interval", 6.0)),
        jitter=float(fe.get("jitter", 3.0)),
        respect_robots=bool(fe.get("respect_robots", True)),
        zotero_url=cfg.get("zotero", {}).get("url", "http://127.0.0.1:23119"),
        zotero_collection_root=cfg.get("zotero", {}).get("collection_root", "research"),
        github_owner=cfg.get("github", {}).get("owner", ""),
        project_template=template,
        registry=Path(_expand(lk.get("registry", "{root}/registry"), lake_root)),
        config_file=path,
        source=source,
        lake_root_from="SB_LAKE_ROOT" if env_root else "project.yaml" if data_root else "config",
        projects_dir=Path(_expand(pdir)).resolve() if pdir else None,
        latex_templates=tuple(sorted((k, str(_hub_path(path.parent, v)))
                                     for k, v in cfg.get("templates", {}).get("latex", {}).items())),
        deliverable_template=cfg.get("templates", {}).get("deliverable") or None,
        library=Path(_expand(cfg.get("library", {}).get("root", "{root}/library"), lake_root)),
        converter=cfg.get("library", {}).get("converter") or None,
    )


def _hub_path(root: Path, value: str) -> Path:
    """Absolute, ~ or relative to the hub root."""
    p = Path(_expand(value))
    return p if p.is_absolute() else (root / p).resolve()


def _project_data_root(start: str | Path | None) -> str | None:
    """`data_root:` of the surrounding project.yaml (absolute, ~ or relative to the project)."""
    root = find_up("project.yaml", start)
    if root is None:
        return None
    try:
        meta = yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    value = meta.get("data_root")
    if not value:
        return None
    p = Path(_expand(str(value)))
    return str(p if p.is_absolute() else (root / p).resolve())


def hub(start: str | Path | None = None, *, required: bool = True) -> Hub | None:
    """Resolved configuration.

    File:      SB_CONFIG -> nearest hub.toml -> user configuration (`sb init`).
    Data root: SB_LAKE_ROOT -> project.yaml `data_root:` -> `lake.root` of that file.
    """
    loc = locate(start)
    if loc is None:
        if required:
            raise FileNotFoundError(
                "no Sourcebound configuration: no hub.toml above the current directory and no "
                f"{user_config_path()} (run `sb init`)")
        return None
    env = tuple(os.environ.get(k) or None for k in ("SB_LAKE_ROOT", "SB_CATALOG", "SB_DATA_PATH"))
    return _load_hub(loc[0], loc[1], _project_data_root(start), env)


@dataclass(frozen=True)
class Project:
    root: Path
    slug: str
    title: str
    lang: str               # "de" | "en"
    meta: dict

    @property
    def schema(self) -> str:
        """Lake schema that belongs to this project (shared domains need contracts)."""
        return f"proj_{self.slug}"

    @property
    def german(self) -> bool:
        return self.lang.startswith("de")


def project(start: str | Path | None = None, *, required: bool = True) -> Project | None:
    root = find_up("project.yaml", start)
    if root is None:
        if required:
            raise FileNotFoundError("no project.yaml found above the current directory")
        return None
    meta = yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8")) or {}
    return Project(root=root, slug=meta["slug"], title=meta.get("title", meta["slug"]),
                   lang=meta.get("lang", "en"), meta=meta)
