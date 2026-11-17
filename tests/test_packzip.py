"""A pack as .zip: checked completely before anything is copied."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def hub(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for k in ("SB_CONFIG", "SB_LAKE_ROOT", "SB_CATALOG", "SB_DATA_PATH"):
        monkeypatch.delenv(k, raising=False)
    h = tmp_path / "hub"
    h.mkdir()
    (h / "hub.toml").write_text("[lake]\nroot = '%s'\n" % (tmp_path / "lake").as_posix(), encoding="utf-8")
    monkeypatch.chdir(h)
    from sourcebound import config
    config._load_hub.cache_clear()
    return h


def make(path: Path, files: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


GOOD = {"pack.yaml": "name: firm\nversion: '2026.11'\n",
        "designs/firm/design.yaml": "name: Firm\ncolors: {primary: '#223344'}\n",
        "designs/firm/logo.png": b"\x89PNG fake",
        "templates/firm-post/template.yaml": "kind: text\ntitle: Firm post\ndesign: firm\n",
        "templates/firm-slides/template.yaml": "kind: slides\ntitle: Slides\ndesign: firm\n",
        "templates/firm-slides/layout.js": "// layout check",
        "README.md": "the firm's pack"}


def test_a_zip_installs_and_is_recorded(tmp_path):
    from sourcebound import assets, config
    done = assets.install_pack(make(tmp_path / "firm.zip", GOOD))
    assert (done["designs"], done["templates"], done["replaced"]) == (["firm"], ["firm-post", "firm-slides"], [])
    reg = config.hub().registry
    assert (reg / "designs" / "firm" / "logo.png").exists() and assets.design("firm")["colors"]["primary"] == "#223344"
    rec = yaml.safe_load((reg / "packs" / "firm.yaml").read_text(encoding="utf-8"))
    assert (rec["version"], rec["templates"]) == ("2026.11", ["firm-post", "firm-slides"])
    again = assets.install_pack(tmp_path / "firm.zip")
    assert again["replaced"] == ["design firm", "template firm-post", "template firm-slides"]


def test_a_zipped_pack_folder_is_accepted(tmp_path):
    from sourcebound import assets
    wrapped = {f"firm-pack/{k}": v for k, v in GOOD.items()}
    assert assets.install_pack(make(tmp_path / "wrapped.zip", wrapped))["designs"] == ["firm"]


@pytest.mark.parametrize("extra, says", [
    ({"designs/firm/../../evil.yaml": "x"}, "path leaves the pack"),
    ({"/abs/design.yaml": "x"}, "path leaves the pack"),
    ({"templates/firm-post/run.py": "print()"}, "file type .py is not allowed"),
    ({"templates/firm-post/tool.exe": b"MZ"}, "file type .exe is not allowed"),
    ({"designs/firm/layout.js": "x"}, "file type .js is not allowed"),        # scripts only in templates
    ({"setup.cfg": "x"}, "only designs/, templates/"),
    ({"designs/other/logo.png": b"x"}, "designs/other: no design.yaml"),
    ({"designs/Bad Id/design.yaml": "x"}, "id `Bad Id`"),
])
def test_refused_zips_install_nothing(tmp_path, extra, says):
    from sourcebound import assets, config
    with pytest.raises(ValueError, match="refused, nothing was installed") as e:
        assets.install_pack(make(tmp_path / "bad.zip", {**GOOD, **extra}))
    assert says in str(e.value)
    assert not (config.hub().registry / "designs" / "firm").exists()


def test_a_zip_bomb_is_refused(tmp_path):
    from sourcebound import assets
    with pytest.raises(ValueError, match="unpacks to"):
        assets.install_pack(make(tmp_path / "bomb.zip", {**GOOD, "designs/firm/big.svg": b"0" * 5_000_000}))


def test_export_as_zip_round_trips(tmp_path):
    from sourcebound import assets, config, packzip
    assets.install_pack(make(tmp_path / "firm.zip", GOOD))
    out = assets.export_pack(tmp_path / "carry.zip", designs_=["firm"], templates_=["firm-post"])
    info = packzip.check(out)
    assert (info["name"], info["designs"], info["templates"]) == ("carry", ["firm"], ["firm-post"])


def _folder(root: Path, files: dict[str, str | bytes]) -> Path:
    for name, data in files.items():
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return root


def test_an_install_records_where_it_came_from_and_a_reinstall_says_what_changed(tmp_path):
    import hashlib

    from sourcebound import assets, config
    reg = config.hub().registry
    z = make(tmp_path / "firm.zip", GOOD)
    first = assets.install_pack(z)
    rec = yaml.safe_load((reg / "packs" / "firm.yaml").read_text(encoding="utf-8"))
    assert rec["source"] == str(z.resolve()) and rec["source_kind"] == "zip"
    assert rec["sha256"] == hashlib.sha256(z.read_bytes()).hexdigest() and len(rec["content_sha256"]) == 64
    assert first["source_differs"] is False and first["changed"] == []

    # the same pack as a folder: same content, so nothing counts as changed
    folder = _folder(tmp_path / "firm-pack", GOOD)
    again = assets.install_pack(folder)
    rec = yaml.safe_load((reg / "packs" / "firm.yaml").read_text(encoding="utf-8"))
    assert (rec["source"], rec["source_kind"]) == (str(folder.resolve()), "folder")
    assert rec["sha256"] == assets.tree_sha256(folder) and again["source_differs"] is False
    assert again["unchanged"] == ["design firm", "template firm-post", "template firm-slides"] and again["changed"] == []

    # one template edited in the folder: the reinstall says so, and names where the old one came from
    (folder / "templates" / "firm-slides" / "layout.js").write_text("// changed", encoding="utf-8")
    (folder / ".DS_Store").write_bytes(b"ignored")                # not part of the hash
    third = assets.install_pack(folder)
    assert third["source_differs"] is True
    assert len(third["changed"]) == 1 and third["changed"][0].startswith("template firm-slides (installed ")
    assert str(folder.resolve()) in third["changed"][0]
    assert (reg / "templates" / "firm-slides" / "layout.js").read_text(encoding="utf-8") == "// changed"


def test_tree_hash_ignores_what_an_install_skips(tmp_path):
    from sourcebound import assets
    a = _folder(tmp_path / "a", {"designs/x/design.yaml": "name: X\n"})
    b = _folder(tmp_path / "b", {"designs/x/design.yaml": "name: X\n", "designs/x/.DS_Store": b"x", "designs/x/~$lock.docx": b"x"})
    assert assets.tree_sha256(a) == assets.tree_sha256(b)
    (b / "designs" / "x" / "design.yaml").write_text("name: Y\n", encoding="utf-8")
    assert assets.tree_sha256(a) != assets.tree_sha256(b)
