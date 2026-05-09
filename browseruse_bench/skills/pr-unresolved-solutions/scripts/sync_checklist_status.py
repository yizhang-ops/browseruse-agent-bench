from __future__ import annotations

import argparse
import logging
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from browseruse_bench.utils import REPO_ROOT


LOGGER = logging.getLogger(__name__)
CHECKBOX_LINE_RE = re.compile(r"^- \[(?P<state>[ xX])\] (?P<thread_id>TH-\d+) \|")


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def run_command(command: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            list(command),
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or "No command output"
        raise RuntimeError(f"Command failed ({' '.join(command)}): {detail}") from exc
    return result.stdout


def resolve_pr_number(pr_number_arg: Optional[int]) -> int:
    if pr_number_arg is not None:
        return pr_number_arg

    try:
        raw = run_command(["gh", "pr", "view", "--json", "number", "--jq", ".number"]).strip()
        if raw:
            return int(raw)
    except (RuntimeError, ValueError):
        LOGGER.info("Failed to detect PR from gh; fallback to latest .pr directory.")

    pr_root = REPO_ROOT / ".pr"
    if not pr_root.exists():
        raise RuntimeError("No .pr directory found and gh PR detection failed.")

    pr_numbers: List[int] = []
    for item in pr_root.iterdir():
        if item.is_dir() and item.name.isdigit():
            pr_numbers.append(int(item.name))

    if not pr_numbers:
        raise RuntimeError("No numeric .pr/<pr_number> directory found.")
    return max(pr_numbers)


def update_checkboxes_in_file(
    file_path: Path,
    thread_ids: Set[str],
    mark_resolved: bool,
    dry_run: bool,
) -> Tuple[int, Set[str]]:
    if not file_path.exists():
        raise RuntimeError(f"Checklist file not found: {file_path}")

    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    updated_lines: List[str] = []
    changed_count = 0
    found_ids: Set[str] = set()
    target_state = "x" if mark_resolved else " "

    for line in lines:
        match = CHECKBOX_LINE_RE.match(line)
        if not match:
            updated_lines.append(line)
            continue

        thread_id = match.group("thread_id")
        if thread_id not in thread_ids:
            updated_lines.append(line)
            continue

        found_ids.add(thread_id)
        current_state = match.group("state")
        if current_state != target_state:
            new_line = CHECKBOX_LINE_RE.sub(f"- [{target_state}] {thread_id} |", line, count=1)
            updated_lines.append(new_line)
            changed_count += 1
        else:
            updated_lines.append(line)

    if changed_count > 0 and not dry_run:
        file_path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")

    return changed_count, found_ids


def validate_thread_ids(thread_ids: List[str]) -> None:
    for thread_id in thread_ids:
        if not re.match(r"^TH-\d+$", thread_id):
            raise ValueError(f"Invalid thread id format: {thread_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync TH-* checkbox state in review_checklist.md and unresolved_checklist.md"
    )
    parser.add_argument("--pr-number", type=int, default=None, help="Target PR number")
    parser.add_argument(
        "--thread-ids",
        nargs="+",
        required=True,
        help="Thread IDs to update, e.g. TH-2773735433 TH-2780379352",
    )
    parser.add_argument(
        "--state",
        choices=("resolved", "unresolved"),
        default="resolved",
        help="Target checkbox state",
    )
    parser.add_argument(
        "--review-checklist",
        type=Path,
        default=None,
        help="Override review checklist path",
    )
    parser.add_argument(
        "--unresolved-checklist",
        type=Path,
        default=None,
        help="Override unresolved checklist path",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)
    validate_thread_ids(args.thread_ids)

    pr_number = resolve_pr_number(args.pr_number)
    pr_dir = REPO_ROOT / ".pr" / str(pr_number)

    review_path = args.review_checklist or (pr_dir / "review_checklist.md")
    unresolved_path = args.unresolved_checklist or (pr_dir / "unresolved_checklist.md")
    mark_resolved = args.state == "resolved"
    thread_ids = set(args.thread_ids)

    changed_review, found_review = update_checkboxes_in_file(
        review_path,
        thread_ids,
        mark_resolved,
        args.dry_run,
    )
    changed_unresolved, found_unresolved = update_checkboxes_in_file(
        unresolved_path,
        thread_ids,
        mark_resolved,
        args.dry_run,
    )

    found_all = found_review | found_unresolved
    missing = sorted(thread_ids - found_all)
    if missing:
        LOGGER.warning("Thread IDs not found in target checklists: %s", ", ".join(missing))

    LOGGER.info(
        "Sync done for PR #%d. review changes=%d, unresolved changes=%d, dry_run=%s",
        pr_number,
        changed_review,
        changed_unresolved,
        args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
