"""Data loader utility for loading datasets from HuggingFace or local files."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from huggingface_hub import hf_hub_download
    from huggingface_hub.utils import (
        EntryNotFoundError,
        HfHubHTTPError,
        RepositoryNotFoundError,
        RevisionNotFoundError,
    )
except ImportError:
    hf_hub_download = None
    EntryNotFoundError = None
    HfHubHTTPError = None
    RepositoryNotFoundError = None
    RevisionNotFoundError = None

try:
    import pandas as pd
except ImportError:
    pd = None

from browseruse_bench.utils.json_io import load_jsonl, load_task_file

HF_DOWNLOAD_EXCEPTIONS: Tuple[type[BaseException], ...] = (OSError, ValueError) + tuple(
    exc
    for exc in (
        HfHubHTTPError,
        EntryNotFoundError,
        RepositoryNotFoundError,
        RevisionNotFoundError,
    )
    if isinstance(exc, type) and issubclass(exc, BaseException)
)

logger = logging.getLogger(__name__)


class DataSource:
    """Data source types."""
    LOCAL = "local"
    HUGGINGFACE = "huggingface"

    @classmethod
    def tolist(cls) -> List[str]:
        return [cls.LOCAL, cls.HUGGINGFACE]


def _check_hf_token(private: bool) -> Optional[str]:
    """Check if HF_TOKEN is available for private datasets.

    Args:
        private: Whether the dataset is private.

    Returns:
        Optional[str]: HF token if available, None otherwise.

    Raises:
        SystemExit: If private dataset requires token but not found.
    """
    if not private:
        return None

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit(
            "[ERROR] Private HuggingFace dataset requires authentication.\n"
            "Please set HF_TOKEN environment variable:\n"
            "  export HF_TOKEN=your_token_here\n"
            "Get your token from: https://huggingface.co/settings/tokens"
        )
    return token


def _download_from_huggingface(
    repo_id: str,
    filename: str,
    private: bool = False,
    revision: Optional[str] = None,
    path_prefix: Optional[str] = None,
    force_download: bool = False
) -> Optional[Path]:
    """Download dataset file from HuggingFace Hub.

    Args:
        repo_id: HuggingFace repository ID (e.g., "Lexmount/LexBench-Browser-Public").
        filename: File name to download (e.g., "task.jsonl").
        private: Whether the dataset is private.
        revision: Git revision (branch, tag, or commit hash).
        path_prefix: Optional path prefix in the repo (e.g., "LexBench-Browser").
        force_download: Whether to force re-download even if cached.

    Returns:
        Optional[Path]: Path to downloaded file in HF cache, or None on failure.
    """

    token = _check_hf_token(private)

    if hf_hub_download is None:
        logger.error(
            "[ERROR] huggingface_hub is not installed. Install with: pip install huggingface_hub"
        )
        return None

    try:
        if path_prefix:
            candidate_path = Path(path_prefix) / filename
        else:
            candidate_path = Path(filename)

        # Prevent absolute paths and path traversal
        if candidate_path.is_absolute() or ".." in candidate_path.parts:
            logger.error("[ERROR] Invalid path for HuggingFace download: %s", candidate_path)
            return None

        # Ensure forward slashes for HF repo paths
        hf_filename = candidate_path.as_posix()

        logger.info(f"[INFO] Downloading from HuggingFace: {repo_id}/{hf_filename}")
        if revision:
            logger.info(f"[INFO] Using revision: {revision}")

        # Download to HuggingFace cache
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=hf_filename,
            repo_type="dataset",
            revision=revision,
            token=token,
            cache_dir=None,  # Use default HF cache
            force_download=force_download
        )

        logger.info(f"[SUCCESS] Downloaded to HF cache: {downloaded_path}")
        return Path(downloaded_path)

    except HF_DOWNLOAD_EXCEPTIONS:
        logger.exception("[ERROR] Failed to download from HuggingFace")
        return None


def _extract_first_present(row: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    """Extract the first non-empty field from a row."""
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if pd is not None:
            try:
                if pd.isna(value):
                    continue
            except (TypeError, ValueError) as exc:
                logger.error("pandas.isna failed for key %s: %s", key, exc)
        value_str = str(value).strip()
        if value_str:
            return value_str
    return None


def _convert_browsecomp_parquet_to_jsonl(parquet_path: Path, jsonl_path: Path) -> bool:
    """Convert BrowseComp parquet file to JSONL with encrypted fields.

    Args:
        parquet_path: Path to parquet file in HF cache.
        jsonl_path: Output JSONL path (usually in HF cache).

    Returns:
        bool: True if conversion succeeded, False otherwise.
    """
    if pd is None:
        logger.error(
            "[ERROR] pandas is not installed.\n"
            "Install it with: pip install pandas"
        )
        return False

    if not parquet_path.exists():
        logger.error(f"[ERROR] Parquet file not found: {parquet_path}")
        return False

    try:
        df = pd.read_parquet(parquet_path)
    except (OSError, ValueError, TypeError) as exc:
        logger.error("[ERROR] Failed to read BrowseComp parquet: %s", exc)
        return False

    if df.empty:
        logger.error("[ERROR] BrowseComp parquet is empty")
        return False

    question_keys = ("encrypted_question", "problem", "question")
    answer_keys = ("encrypted_answer", "answer", "solution")
    canary_keys = ("canary",)
    id_keys = ("task_id", "id")

    records = df.to_dict(orient="records")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    with jsonl_path.open("w", encoding="utf-8") as f:
        for idx, row in enumerate(records):
            encrypted_question = None
            prompt_raw = row.get("prompt")
            if isinstance(prompt_raw, dict):
                encrypted_question = prompt_raw.get("content")
            else:
                if isinstance(prompt_raw, (list, tuple)):
                    for item in prompt_raw:
                        if isinstance(item, dict) and item.get("content"):
                            encrypted_question = item["content"]
                            break

            if not encrypted_question:
                encrypted_question = _extract_first_present(row, question_keys)

            extra_raw = row.get("extra")
            extra: Dict[str, Any] = {}
            if isinstance(extra_raw, str):
                try:
                    extra = json.loads(extra_raw)
                except json.JSONDecodeError:
                    extra = {}
            elif isinstance(extra_raw, dict):
                extra = extra_raw

            encrypted_answer = _extract_first_present(extra, answer_keys)
            canary = _extract_first_present(extra, canary_keys)

            task_id = _extract_first_present(row, id_keys)
            uuid = row.get("uuid")
            if not task_id and uuid is not None:
                uuid_str = str(uuid)
                match = re.match(r"browsecomp-(\d+)$", uuid_str)
                if match:
                    task_id = f"browsecomp_{int(match.group(1)):03d}"
                else:
                    task_id = uuid_str

            if not task_id:
                task_id = f"browsecomp_{idx:03d}"

            if not encrypted_question or not encrypted_answer or not canary:
                skipped += 1
                continue

            task_obj = {
                "task_id": task_id,
                "encrypted_question": encrypted_question,
                "encrypted_answer": encrypted_answer,
                "canary": canary,
            }
            f.write(json.dumps(task_obj, ensure_ascii=False) + "\n")
            written += 1

    if written == 0:
        logger.error("[ERROR] No valid BrowseComp rows found in parquet")
        return False

    if skipped > 0:
        logger.warning("[WARNING] Skipped %s rows with missing fields", skipped)

    logger.info(f"[SUCCESS] Converted BrowseComp parquet to JSONL: {jsonl_path}")
    return True


def _resolve_hf_config(hf_config: Dict[str, Any], split: Optional[str] = None, benchmark_name: Optional[str] = None) -> Dict[str, Any]:
    """Resolve HuggingFace config for a specific split.

    Args:
        hf_config: HuggingFace configuration from data_info.json.
        split: Dataset split name (e.g., "All").
        benchmark_name: Optional benchmark name to select specific config.

    Returns:
        Dict[str, Any]: Resolved HF config for the split.
    """
    if benchmark_name and benchmark_name in hf_config:
        hf_config = hf_config[benchmark_name]
    # Base config is the top-level (minus 'splits' and 'default' if present)
    base_config = {k: v for k, v in hf_config.items() if k not in ["splits", "default"]}

    # If explicit 'default' key exists, it overrides top-level as base
    if "default" in hf_config:
        base_config.update(hf_config["default"])

    if not split or "splits" not in hf_config:
        return base_config

    splits = hf_config["splits"]

    # Check for direct match first
    if split in splits:
        base_config.update(splits[split])
        return base_config

    # Check for comma-separated match
    for keys_str, config in splits.items():
        keys = [k.strip() for k in keys_str.split(',')]
        if split in keys:
            base_config.update(config)
            return base_config

    return base_config


def load_dataset_file(
    local_path: Path,
    data_info: Dict[str, Any],
    data_source: str = DataSource.LOCAL,
    force_download: bool = False,
    split: Optional[str] = None,
    benchmark_name: Optional[str] = None
) -> Path:
    """Load dataset file from local or remote source.

    Args:
        local_path: Local file path (e.g., browseruse_bench/data/LexBench-Browser/task.jsonl).
        data_info: Content of data_info.json containing HF or BrowseComp config.
        data_source: Data source type ("local" or "huggingface").
        force_download: Force re-download from HuggingFace even if cached.
        split: Dataset split name (e.g., "All").

    Returns:
        Path: Path to the dataset file (local).

    Raises:
        SystemExit: If file not found and cannot download.
    """
    # Force local mode
    if data_source == DataSource.LOCAL:
        if force_download:
            logger.warning("[WARNING] --force-download is ignored in local mode")
        if not local_path.exists():
            raise SystemExit(f"[ERROR] Local file not found: {local_path}")
        logger.info(f"[INFO] Using local dataset: {local_path}")
        return local_path

    # Force download mode
    if data_source == DataSource.HUGGINGFACE:
        is_browsecomp = "browsecomp" in data_info
        browsecomp_config = data_info.get("browsecomp", {}) if is_browsecomp else {}
        hf_config_raw = data_info.get("huggingface")
        hf_config = _resolve_hf_config(hf_config_raw, split, benchmark_name) if hf_config_raw else None

        if is_browsecomp:
            hf_repo_id = browsecomp_config.get("hf_repo_id") or (hf_config or {}).get("repo_id")
            hf_filename = browsecomp_config.get("hf_filename") or local_path.name
            hf_path_prefix = browsecomp_config.get("hf_path_prefix") or (hf_config or {}).get("path_prefix")
            hf_revision = browsecomp_config.get("hf_revision") or (hf_config or {}).get("revision")
            hf_private = browsecomp_config.get("hf_private")
            if hf_private is None:
                hf_private = (hf_config or {}).get("private", False)

            if not hf_repo_id:
                raise SystemExit(
                    "[ERROR] BrowseComp HuggingFace config missing.\n"
                    "Please set browsecomp.hf_repo_id in data_info.json."
                )

            downloaded_path = _download_from_huggingface(
                repo_id=hf_repo_id,
                filename=hf_filename,
                private=hf_private,
                revision=hf_revision,
                path_prefix=hf_path_prefix,
                force_download=force_download,
            )
            if downloaded_path is None:
                raise SystemExit("[ERROR] Failed to download BrowseComp dataset")

            if downloaded_path.suffix == ".parquet":
                jsonl_path = downloaded_path.with_suffix(".jsonl")
                if jsonl_path.exists() and not force_download:
                    logger.info(f"[INFO] Using cached BrowseComp JSONL: {jsonl_path}")
                    return jsonl_path
                if not _convert_browsecomp_parquet_to_jsonl(downloaded_path, jsonl_path):
                    raise SystemExit("[ERROR] Failed to convert BrowseComp parquet to JSONL")
                return jsonl_path

            return downloaded_path

        if not hf_config:
            raise SystemExit(
                "[ERROR] No HuggingFace config found in data_info.json.\n"
                "Cannot download without configuration."
            )

        downloaded_path = _download_from_huggingface(
            repo_id=hf_config["repo_id"],
            filename=local_path.name,
            private=hf_config.get("private", False),
            revision=hf_config.get("revision"),
            path_prefix=hf_config.get("path_prefix"),
            force_download=force_download
        )
        if downloaded_path is None:
            raise SystemExit("[ERROR] Failed to download dataset")
        return downloaded_path

    raise ValueError(f"Unknown data_source: {data_source}")
