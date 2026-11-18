"""Toolkits: an organisation's code found, checked and run in its own environment; pack requirements."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sourcebound import plugins, toolkits


@pytest.fixture()
def kit(tmp_path, monkeypatch):
    root = tmp_path / "firm-lib"
    (root / "skills" / "charts" / "scripts").mkdir(parents=True)
    (root / "skills" / "charts" / "SKILL.md").write_text("---\nname: charts\n---\n", encoding="utf-8")
    (root / "skills" / "charts" / "scripts" / "hello.py").write_text(
        "import os, sys\nprint(os.environ['UV_PROJECT_ENVIRONMENT'], os.environ.get('FIRM'), *sys.argv[1:])\n", encoding="utf-8")
    reg = plugins.Registry()
    api = plugins.Api(plugins.Plugin("firm"), reg)
    api.toolkit("firm-lib", title="Firm", find=lambda: root, python=lambda r: Path(sys.executable),
                env=lambda r: {"FIRM": "yes"}, checks=lambda r: [("warning", "no database settings")])
    monkeypatch.setattr(plugins, "_REGISTRY", reg)
    return root


def test_status_lists_skills_and_checks(kit):
    st = toolkits.status("firm-lib")
    assert st.ok and st.root == kit
    assert list(st.skills) == ["charts"]
    assert st.warnings == ["no database settings"]


def test_run_uses_the_toolkits_environment(kit):
    done = toolkits.run("firm-lib", "skill:charts/scripts/hello.py", ["a"], capture=True)
    assert done.returncode == 0
    venv, firm, arg = done.stdout.split()
    assert Path(venv) == Path(sys.executable).parent.parent        # never Sourcebound's own UV_PROJECT_ENVIRONMENT
    assert (firm, arg) == ("yes", "a")


def test_missing_checkout_and_unknown_skill(kit, monkeypatch):
    with pytest.raises(FileNotFoundError):
        toolkits.script_path(toolkits.status("firm-lib"), "skill:nope/x.py")
    plugins._REGISTRY.toolkits["firm-lib"].find = lambda: None
    st = toolkits.status("firm-lib")
    assert not st.ok and "not found" in st.errors[0]
    with pytest.raises(RuntimeError):
        toolkits.run("firm-lib", "skill:charts/scripts/hello.py", [])


def test_requirements(kit, monkeypatch):
    monkeypatch.setattr(toolkits, "claude_plugin_skills", lambda: {"firm:charts": Path("x")})
    out = dict((text, ok) for ok, text in toolkits.requirements(
        {"requires": {"toolkits": ["firm-lib", "other"], "skills": ["firm:charts", "firm:report"]}}))
    assert out[f"toolkit firm-lib at {kit}"] is True
    assert any(t.startswith("toolkit other") and not ok for t, ok in out.items())
    assert out["skill firm:charts"] is True
    assert any(t.startswith("skill firm:report") and not ok for t, ok in out.items())
