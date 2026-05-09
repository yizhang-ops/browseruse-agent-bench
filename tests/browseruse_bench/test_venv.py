"""Tests for browseruse_bench.utils.venv."""

from __future__ import annotations

from pathlib import Path

import pytest

from browseruse_bench.utils import venv as venv_utils


def test_resolve_agent_venv_path_requires_venv_field() -> None:
    with pytest.raises(SystemExit, match="must define a non-empty 'venv' path"):
        venv_utils.resolve_agent_venv_path({})


def test_resolve_agent_venv_path_requires_non_empty_venv() -> None:
    with pytest.raises(SystemExit, match="must define a non-empty 'venv' path"):
        venv_utils.resolve_agent_venv_path({"venv": "   "})


def test_resolve_agent_venv_path_resolves_relative_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(venv_utils, "REPO_ROOT", tmp_path)

    resolved = venv_utils.resolve_agent_venv_path({"venv": ".venvs/browser_use"})

    assert resolved == tmp_path / ".venvs/browser_use"


def test_resolve_agent_venv_path_keeps_absolute_path() -> None:
    resolved = venv_utils.resolve_agent_venv_path({"venv": "/tmp/agent-venv"})
    assert resolved == Path("/tmp/agent-venv")
