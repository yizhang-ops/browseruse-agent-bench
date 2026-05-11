from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Iterable

from huggingface_hub import HfApi, hf_hub_download

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "browseruse_bench" / "data" / "LexBench-Browser"
DATASET_CARD = ROOT / "community" / "huggingface" / "dataset-card.md"

EXPECTED_DATA_FILES = (
    "data_info.json",
    "task.jsonl",
    "task_global.jsonl",
    "task_lexmount.jsonl",
    "VERSION_HISTORY.md",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_jsonl(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} is not valid JSONL: {exc}") from exc
            count += 1
    return count


def _load_dataset_config() -> dict:
    data_info_path = DATASET_DIR / "data_info.json"
    with data_info_path.open(encoding="utf-8") as file:
        return json.load(file)


def _validate_local_files() -> tuple[str, str, list[Path]]:
    if not DATASET_DIR.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {DATASET_DIR}")
    if not DATASET_CARD.is_file():
        raise FileNotFoundError(f"Dataset card not found: {DATASET_CARD}")

    config = _load_dataset_config()
    hf_config = config["huggingface"]["LexBench-Browser"]
    repo_id = hf_config["repo_id"]
    path_prefix = hf_config.get("path_prefix", "LexBench-Browser").strip("/")

    local_files = [DATASET_DIR / name for name in EXPECTED_DATA_FILES]
    for path in local_files:
        if not path.is_file():
            raise FileNotFoundError(f"Expected dataset file not found: {path}")

    split_counts = {
        "task.jsonl": _count_jsonl(DATASET_DIR / "task.jsonl"),
        "task_global.jsonl": _count_jsonl(DATASET_DIR / "task_global.jsonl"),
        "task_lexmount.jsonl": _count_jsonl(DATASET_DIR / "task_lexmount.jsonl"),
    }
    logger.info(
        "Validated local JSONL files: task=%s, global=%s, lexmount=%s",
        split_counts["task.jsonl"],
        split_counts["task_global.jsonl"],
        split_counts["task_lexmount.jsonl"],
    )

    expected_total = config["version_info"]["LexBench-Browser"]["total_tasks"]
    if split_counts["task.jsonl"] != expected_total:
        raise ValueError(
            f"task.jsonl has {split_counts['task.jsonl']} rows; expected {expected_total}"
        )

    return repo_id, path_prefix, local_files


def _verify_remote(
    repo_id: str,
    path_prefix: str,
    local_files: Iterable[Path],
    token: str | None,
) -> None:
    for local_path in local_files:
        remote_name = f"{path_prefix}/{local_path.name}"
        downloaded = Path(
            hf_hub_download(
                repo_id=repo_id,
                repo_type="dataset",
                filename=remote_name,
                force_download=True,
                token=token,
            )
        )
        if _sha256(local_path) != _sha256(downloaded):
            raise ValueError(f"Remote file differs from local file: {remote_name}")
        logger.info("Verified remote file: %s", remote_name)

    downloaded_card = Path(
        hf_hub_download(
            repo_id=repo_id,
            repo_type="dataset",
            filename="README.md",
            force_download=True,
            token=token,
        )
    )
    if _sha256(DATASET_CARD) != _sha256(downloaded_card):
        raise ValueError("Remote README.md differs from local dataset card")
    logger.info("Verified remote file: README.md")


def sync_dataset(*, token: str | None, yes: bool, verify: bool) -> None:
    repo_id, path_prefix, local_files = _validate_local_files()
    logger.info("Target Hugging Face dataset: %s", repo_id)

    if not yes:
        logger.info("Dry run complete. Pass --yes to upload to Hugging Face.")
        return
    if not token:
        raise ValueError("HF_TOKEN is required when --yes is used")

    api = HfApi()
    api.whoami(token=token)

    dataset_commit = api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        token=token,
        folder_path=DATASET_DIR,
        path_in_repo=path_prefix,
        delete_patterns=f"{path_prefix}/*",
        commit_message="Update LexBench-Browser dataset files",
        commit_description="Sync dataset files from browseruse-agent-bench repository.",
    )
    logger.info("Dataset files commit: %s", dataset_commit.oid)

    card_commit = api.upload_file(
        repo_id=repo_id,
        repo_type="dataset",
        token=token,
        path_or_fileobj=DATASET_CARD,
        path_in_repo="README.md",
        commit_message="Update dataset card",
        commit_description="Sync dataset card from browseruse-agent-bench repository.",
    )
    logger.info("Dataset card commit: %s", card_commit.oid)

    if verify:
        _verify_remote(repo_id, path_prefix, local_files, token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync LexBench-Browser data to Hugging Face.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Upload to Hugging Face. Without this flag, only local validation runs.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip downloading uploaded files for hash verification.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sync_dataset(token=os.environ.get("HF_TOKEN"), yes=args.yes, verify=not args.no_verify)


if __name__ == "__main__":
    main()
