from __future__ import annotations

import json
from pathlib import Path

import pytest

from browseruse_bench.browsers import orphan_cleanup as orphan_cleanup_module


def test_remove_state_file_returns_false_on_oserror(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state_dir"
    state_dir.mkdir()

    assert orphan_cleanup_module._remove_state_file(state_dir) is False
    assert state_dir.exists()


def test_cleanup_returns_failure_when_remove_state_file_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps({"backend_id": "unknown", "session_id": "session-1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(orphan_cleanup_module, "_remove_state_file", lambda path: False)

    result = orphan_cleanup_module.cleanup_orphaned_session_state(state_file)

    assert result == 1


def test_cleanup_returns_success_when_state_file_removed(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps({"backend_id": "unknown", "session_id": "session-1"}),
        encoding="utf-8",
    )

    result = orphan_cleanup_module.cleanup_orphaned_session_state(state_file)

    assert result == 0
    assert not state_file.exists()
