"""`sb deliver`: render, convert and collect into one folder; nothing is sent."""
from __future__ import annotations

import email
import email.policy
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Never read the developer's own configuration or lake."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    for k in ("SB_CONFIG", "SB_LAKE_ROOT", "SB_CATALOG", "SB_DATA_PATH"):
        monkeypatch.delenv(k, raising=False)
    from sourcebound import lake
    lake._CON = None
    yield
    lake._CON = None


@pytest.fixture()
def hub(tmp_path, monkeypatch):
    h = tmp_path / "hub"
    h.mkdir()
    (h / "hub.toml").write_text("[lake]\nroot = '%s'\n[fetch]\nmin_interval = 0.0\njitter = 0.0\n[templates]\nproject = '%s'\n"
                                % ((tmp_path / "lake").as_posix(), (ROOT / "templates" / "project").as_posix()), encoding="utf-8")
    monkeypatch.chdir(h)
    from sourcebound import config
    config._load_hub.cache_clear()
    return h


@pytest.fixture()
def piece(hub, monkeypatch):
    from sourcebound.cli import main
    main(["new", "topic", "--title", "A Topic", "--kind", "desk", "--lang", "de"])
    monkeypatch.chdir(hub / "topic")
    main(["piece", "add", "Grosse", "Bewegungen", "--kind", "post", "--id", "p1", "--template", "text"])
    (hub / "topic" / "pieces" / "p1" / "text.md").write_text("# Titel\n\nEin Satz ohne Quelle.\n", encoding="utf-8")
    return hub / "topic"


def test_deliver_collects_renders_with_a_manifest_and_an_unsent_mail(piece):
    from sourcebound import deliver, plugins
    reg = plugins.load(fresh=True)
    seen = []

    def fake_pdf(path, out):                       # stands in for Word: a .txt "converted" to .pdf
        seen.append(Path(path).name)
        Path(out).write_bytes(b"%PDF-1.4 test")
        return Path(out), ["converted by the test"]

    plugins.Api(plugins.Plugin("testconv"), reg).converter(".docx", ".pdf", fake_pdf)
    try:
        m = deliver.deliver("p1", ["text", "markdown"], email="team@example.org", zip_it=True)
    finally:
        plugins.load(fresh=True)
    out = Path(m["folder"])
    assert out.parent == piece / "dist" / "deliver" and out.name.startswith("p1-")
    names = sorted(f["file"] for f in m["files"])
    assert names == ["markdown__p1.md", "p1.eml", "text__p1.txt"] and seen == []      # no .docx, nothing converted
    for f in m["files"]:
        assert f["sha256"] == hashlib.sha256((out / f["file"]).read_bytes()).hexdigest()
    on_disk = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    assert on_disk["target"] == "pieces/p1" and on_disk["for_review_only"] and on_disk["status"] == "idea"
    assert "FOR REVIEW" in (out / "README.txt").read_text(encoding="utf-8")
    mail = email.message_from_bytes((out / "p1.eml").read_bytes(), policy=email.policy.default)
    assert (mail["X-Unsent"], mail["To"], mail["Subject"]) == ("1", "team@example.org", "Grosse Bewegungen")
    assert "Ein Satz ohne Quelle." in mail.get_body(("plain",)).get_content()
    assert Path(m["zip"]).exists()


def test_deliver_refuses_pdf_without_a_converter(piece):
    from sourcebound import deliver, plugins
    reg = plugins.load(fresh=True)
    reg.converters.clear()                          # as if the Word plugin were not installed
    try:
        with pytest.raises(RuntimeError, match=r"no converter for \.docx -> \.pdf"):
            deliver.deliver("p1", ["text"], pdf=True)
    finally:
        plugins.load(fresh=True)


def test_deliver_uses_the_piece_template_by_default(piece):
    from sourcebound import deliver
    m = deliver.deliver("p1", [])
    assert [r["template"] for r in m["renders"]] == ["text"] and "email" not in json.dumps(m["files"])
