from __future__ import annotations

from scripts.sync_hf_dataset import _validate_local_files


def test_validate_local_files() -> None:
    repo_id, path_prefix, local_files = _validate_local_files()

    assert repo_id == "Lexmount/LexBench-Browser"
    assert path_prefix == "LexBench-Browser"
    assert {path.name for path in local_files} == {
        "VERSION_HISTORY.md",
        "data_info.json",
        "task.jsonl",
        "task_global.jsonl",
        "task_lexmount.jsonl",
    }
