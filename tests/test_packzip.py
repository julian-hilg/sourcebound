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
