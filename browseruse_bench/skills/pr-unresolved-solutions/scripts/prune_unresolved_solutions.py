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
SECTION_RE = re.compile(r"^### (TH-\d+)\s*$", re.MULTILINE)
REVIEWER_RE = re.compile(r"^- Reviewer: `(?P<reviewer>[^`]+)`\s*$", re.MULTILINE)
CATEGORY_RE = re.compile(r"^- 分类标记: (?P<category>.+)\s*$", re.MULTILINE)


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


def validate_thread_ids(thread_ids: List[str]) -> None:
    for thread_id in thread_ids:
        if not re.match(r"^TH-\d+$", thread_id):
            raise ValueError(f"Invalid thread id format: {thread_id}")


def parse_thread_states(checklist_path: Path) -> Dict[str, bool]:
    if not checklist_path.exists():
        raise RuntimeError(f"Checklist file not found: {checklist_path}")

    states: Dict[str, bool] = {}
    for line in checklist_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = CHECKBOX_LINE_RE.match(line)
        if not match:
            continue
        thread_id = match.group("thread_id")
        states[thread_id] = match.group("state").lower() == "x"
    return states


def parse_section_spans(content: str) -> List[Tuple[str, int, int]]:
    matches = list(SECTION_RE.finditer(content))
    spans: List[Tuple[str, int, int]] = []
    for idx, match in enumerate(matches):
        thread_id = match.group(1)
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        spans.append((thread_id, start, end))
    return spans


def prune_sections(content: str, target_thread_ids: Set[str]) -> Tuple[str, int]:
    spans = parse_section_spans(content)
    if not spans:
        return content, 0

    header = content[: spans[0][1]]
    kept_sections: List[str] = []
    pruned_count = 0
    for thread_id, start, end in spans:
        if thread_id in target_thread_ids:
            pruned_count += 1
            continue
        kept_sections.append(content[start:end])

    if not kept_sections:
        return header.rstrip() + "\n", pruned_count

    normalized_header = header.rstrip() + "\n\n"
    body = "".join(kept_sections).lstrip("\n")
    return (normalized_header + body).rstrip() + "\n", pruned_count


def summarize_sections(content: str) -> Tuple[int, Dict[str, int], int, int]:
    section_spans = parse_section_spans(content)
    reviewer_counts: Dict[str, int] = {}
    direct_close_count = 0
    need_direction_count = 0

    for _, start, end in section_spans:
        section_text = content[start:end]
        reviewer_match = REVIEWER_RE.search(section_text)
        reviewer = reviewer_match.group("reviewer") if reviewer_match else "unknown"
        reviewer_counts[reviewer] = reviewer_counts.get(reviewer, 0) + 1

        category_match = CATEGORY_RE.search(section_text)
        category = category_match.group("category") if category_match else ""
        if "建议直接关闭" in category:
            direct_close_count += 1
        elif "建议先定方向再改" in category:
            need_direction_count += 1

    total = len(section_spans)
    return total, reviewer_counts, direct_close_count, need_direction_count


def update_summary_metadata(content: str) -> str:
    total, reviewer_counts, direct_close_count, need_direction_count = summarize_sections(content)
    code_doc_change_count = total - direct_close_count - need_direction_count

    lines = content.splitlines()
    result_lines: List[str] = []
    reviewer_line_seen = False

    for line in lines:
        if line.startswith("- Total unresolved threads: "):
            result_lines.append(f"- Total unresolved threads: {total}")
            continue

        if line.startswith("- Reviewer breakdown: "):
            reviewer_line_seen = True
            if reviewer_counts:
                summary = ", ".join(
                    f"{reviewer}={count}" for reviewer, count in sorted(reviewer_counts.items())
                )
                result_lines.append(f"- Reviewer breakdown: {summary}")
            continue

        if line.startswith("- Generation mode: "):
            result_lines.append(line)
            continue

        if line.startswith("- <span style=\"color:#d32f2f;\"><strong>建议直接关闭（已被后续重构覆盖）: "):
            result_lines.append(
                f"- <span style=\"color:#d32f2f;\"><strong>建议直接关闭（已被后续重构覆盖）: {direct_close_count}</strong></span>"
            )
            continue

        if line.startswith("- `建议改动代码/文档`: "):
            result_lines.append(f"- `建议改动代码/文档`: {code_doc_change_count}")
            continue

        if line.startswith("- `建议先定方向再改（产品/规范决策）`: "):
            result_lines.append(f"- `建议先定方向再改（产品/规范决策）`: {need_direction_count}")
            continue

        result_lines.append(line)

    if reviewer_counts and not reviewer_line_seen:
        reviewer_summary = ", ".join(
            f"{reviewer}={count}" for reviewer, count in sorted(reviewer_counts.items())
        )
        insert_index = next(
            (
                idx + 1
                for idx, line in enumerate(result_lines)
                if line.startswith("- Generation mode: ")
            ),
            -1,
        )
        if insert_index < 0:
            insert_index = next(
                (
                    idx + 1
                    for idx, line in enumerate(result_lines)
                    if line.startswith("- Total unresolved threads: ")
                ),
                len(result_lines),
            )
        result_lines.insert(insert_index, f"- Reviewer breakdown: {reviewer_summary}")

    return "\n".join(result_lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prune resolved TH-* sections from unresolved_solutions.md based on "
            "unresolved_checklist.md checkbox state."
        )
    )
    parser.add_argument("--pr-number", type=int, default=None, help="Target PR number")
    parser.add_argument(
        "--solutions",
        type=Path,
        default=None,
        help="Path to unresolved_solutions.md (default: .pr/<pr>/unresolved_solutions.md)",
    )
    parser.add_argument(
        "--unresolved-checklist",
        type=Path,
        default=None,
        help="Path to unresolved_checklist.md (default: .pr/<pr>/unresolved_checklist.md)",
    )
    parser.add_argument(
        "--thread-ids",
        nargs="*",
        default=None,
        help="Optional TH-* list to prune. Only resolved IDs in checklist will be pruned.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview prune result without writing file")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)

    selected_ids = args.thread_ids or []
    if selected_ids:
        validate_thread_ids(selected_ids)

    pr_number = resolve_pr_number(args.pr_number)
    pr_dir = REPO_ROOT / ".pr" / str(pr_number)

    solutions_path = args.solutions or (pr_dir / "unresolved_solutions.md")
    unresolved_checklist_path = args.unresolved_checklist or (pr_dir / "unresolved_checklist.md")

    if not solutions_path.exists():
        raise RuntimeError(f"Solutions file not found: {solutions_path}")

    thread_states = parse_thread_states(unresolved_checklist_path)
    resolved_ids = {thread_id for thread_id, is_resolved in thread_states.items() if is_resolved}
    if selected_ids:
        target_ids = {thread_id for thread_id in selected_ids if thread_states.get(thread_id) is True}
        skipped = sorted(set(selected_ids) - target_ids)
        if skipped:
            LOGGER.warning(
                "Skip non-resolved or missing thread IDs (not pruned): %s",
                ", ".join(skipped),
            )
    else:
        target_ids = resolved_ids

    if not target_ids:
        LOGGER.info("No resolved thread IDs to prune for PR #%d.", pr_number)
        return 0

    content = solutions_path.read_text(encoding="utf-8", errors="replace")
    pruned_content, pruned_count = prune_sections(content, target_ids)
    updated_content = update_summary_metadata(pruned_content)

    if pruned_count == 0:
        LOGGER.info("No matching TH-* sections found in %s.", solutions_path)
        return 0

    if not args.dry_run:
        solutions_path.write_text(updated_content, encoding="utf-8")

    total, reviewer_counts, _, _ = summarize_sections(updated_content)
    reviewer_summary = ", ".join(
        f"{reviewer}={count}" for reviewer, count in sorted(reviewer_counts.items())
    )
    LOGGER.info(
        "Pruned %d resolved section(s) from %s (remaining=%d, dry_run=%s, reviewers=%s)",
        pruned_count,
        solutions_path,
        total,
        args.dry_run,
        reviewer_summary or "none",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
