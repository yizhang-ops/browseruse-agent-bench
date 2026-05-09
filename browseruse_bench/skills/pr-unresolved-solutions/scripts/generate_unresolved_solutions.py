from __future__ import annotations

import argparse
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from browseruse_bench.utils import REPO_ROOT


LOGGER = logging.getLogger(__name__)

INDEX_LINE_RE = re.compile(r"^- \[(?P<state>[ xX])\] (?P<thread_id>TH-\d+) \| `(?P<file>[^`]+)` \| (?P<meta>.+)$")
SECTION_RE = re.compile(r"^### (TH-\d+)\s*$", re.MULTILINE)
RAW_CHAT_ITEM_RE = re.compile(
    r"- (?P<author>[^|\n]+) \| [^\n]*\n\n````text\n(?P<body>.*?)\n````",
    re.DOTALL,
)


@dataclass(frozen=True)
class ThreadIndexItem:
    thread_id: str
    file_path: str
    reviewer: str
    thread_url: str
    outdated: bool
    checked: bool
    comment_excerpt: str


class ThreadCategory:
    DIRECT_CLOSE = "direct_close"
    CODE_DOC_CHANGE = "code_doc_change"
    NEED_DIRECTION = "need_direction"


@dataclass(frozen=True)
class PreservedProposal:
    initial: List[str]
    planned: List[str]
    validation: List[str]
    handling_label: Optional[str]
    status_label: Optional[str]


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


def parse_index_items(lines: List[str], section_map: Dict[str, str]) -> List[ThreadIndexItem]:
    in_index = False
    items: List[ThreadIndexItem] = []

    for line in lines:
        if line.startswith("## Index"):
            in_index = True
            continue
        if in_index and line.startswith("## ") and not line.startswith("## Index"):
            break
        if not in_index:
            continue

        match = INDEX_LINE_RE.match(line.strip())
        if not match:
            continue

        thread_id = match.group("thread_id")
        checked = match.group("state").lower() == "x"
        file_path = match.group("file")
        meta_raw = match.group("meta")
        meta_tokens = [token.strip() for token in meta_raw.split("|")]

        reviewer = "unknown"
        thread_url = ""
        outdated = False

        for token in meta_tokens:
            if token == "outdated":
                outdated = True
                continue
            if token.startswith("root="):
                reviewer = token.split("=", maxsplit=1)[1].strip()
                continue
            if token.startswith("[thread](") and token.endswith(")"):
                thread_url = token[len("[thread](") : -1]

        excerpt = extract_comment_excerpt(section_map.get(thread_id, ""), reviewer)
        items.append(
            ThreadIndexItem(
                thread_id=thread_id,
                file_path=file_path,
                reviewer=reviewer,
                thread_url=thread_url,
                outdated=outdated,
                checked=checked,
                comment_excerpt=excerpt,
            )
        )

    return items


def parse_thread_sections(content: str) -> Dict[str, str]:
    matches = list(SECTION_RE.finditer(content))
    sections: Dict[str, str] = {}
    for idx, match in enumerate(matches):
        thread_id = match.group(1)
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        sections[thread_id] = content[start:end]
    return sections


def extract_comment_excerpt(section_text: str, reviewer: str) -> str:
    if not section_text:
        return "N/A"

    raw_chat_pos = section_text.find("Raw chat log:")
    if raw_chat_pos < 0:
        return "N/A"

    raw_chat_text = section_text[raw_chat_pos:]
    comments = []
    for match in RAW_CHAT_ITEM_RE.finditer(raw_chat_text):
        author = match.group("author").strip()
        body = compress_text(match.group("body"))
        comments.append((author, body))

    if not comments:
        return "N/A"

    for author, body in comments:
        if author == reviewer:
            return f"{author}: {truncate_text(body, 220)}"

    first_author, first_body = comments[0]
    return f"{first_author}: {truncate_text(first_body, 220)}"


def truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def compress_text(value: str) -> str:
    return " ".join(value.split())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate unresolved solution scaffolding from .pr/<pr>/unresolved_checklist.md. "
            "Agent must fill concrete solution details manually."
        )
    )
    parser.add_argument("--pr-number", type=int, default=None, help="Target PR number")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Input unresolved checklist path (default: .pr/<pr>/unresolved_checklist.md)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: .pr/<pr>/unresolved_solutions.md)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing output file",
    )
    parser.add_argument(
        "--reset-all",
        action="store_true",
        help="When used with --overwrite, discard existing thread proposals and regenerate scaffold only",
    )
    parser.add_argument(
        "--direct-close-thread-ids",
        nargs="*",
        default=None,
        help="Thread IDs forced into direct-close category (default also includes outdated threads)",
    )
    parser.add_argument(
        "--decision-thread-ids",
        nargs="*",
        default=None,
        help="Thread IDs forced into need-direction category",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    return parser.parse_args()


def classify_threads(
    items: List[ThreadIndexItem],
    direct_close_ids: Set[str],
    decision_ids: Set[str],
) -> Dict[str, str]:
    category_map: Dict[str, str] = {}
    for item in items:
        if item.thread_id in decision_ids:
            category_map[item.thread_id] = ThreadCategory.NEED_DIRECTION
        elif item.thread_id in direct_close_ids or item.outdated:
            category_map[item.thread_id] = ThreadCategory.DIRECT_CLOSE
        else:
            category_map[item.thread_id] = ThreadCategory.CODE_DOC_CHANGE
    return category_map


def format_category_label(category: str) -> str:
    if category == ThreadCategory.DIRECT_CLOSE:
        return "<span style=\"color:#d32f2f;\"><strong>建议直接关闭</strong></span>"
    if category == ThreadCategory.NEED_DIRECTION:
        return "`建议先定方向再改`"
    return "`建议改动代码/文档`"


def format_handling_label(category: str) -> str:
    if category == ThreadCategory.DIRECT_CLOSE:
        return "<span style=\"color:#d32f2f;\"><strong>Close as obsolete</strong></span>"
    if category == ThreadCategory.NEED_DIRECTION:
        return "`Need maintainer decision`"
    return "`Code/docs patch`"


def normalize_file_path(file_path_with_line: str) -> str:
    path = file_path_with_line
    if ":" in path:
        path = path.rsplit(":", maxsplit=1)[0]
    return path


def parse_preserved_proposals(content: str) -> Dict[str, PreservedProposal]:
    proposals: Dict[str, PreservedProposal] = {}
    section_map = parse_thread_sections(content)

    for thread_id, section_text in section_map.items():
        initial: List[str] = []
        planned: List[str] = []
        validation: List[str] = []
        handling_label: Optional[str] = None
        status_label: Optional[str] = None
        current_block: Optional[str] = None

        for raw_line in section_text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()

            if stripped == "- Initial Solution Proposal:":
                current_block = "initial"
                continue
            if stripped == "- Planned Changes:":
                current_block = "planned"
                continue
            if stripped == "- Validation:":
                current_block = "validation"
                continue
            if stripped.startswith("- 建议处理: "):
                handling_label = stripped[len("- 建议处理: ") :].strip()
                current_block = None
                continue
            if stripped.startswith("- Status: "):
                status_label = stripped[len("- Status: ") :].strip()
                current_block = None
                continue
            if stripped.startswith("- "):
                current_block = None
                continue
            if not line.startswith("  - ") or current_block is None:
                continue

            entry = line[len("  - ") :].strip()
            if not entry:
                continue
            if current_block == "initial":
                initial.append(entry)
            elif current_block == "planned":
                planned.append(entry)
            elif current_block == "validation":
                validation.append(entry)

        if initial or planned or validation or handling_label or status_label:
            proposals[thread_id] = PreservedProposal(
                initial=initial,
                planned=planned,
                validation=validation,
                handling_label=handling_label,
                status_label=status_label,
            )

    return proposals


def build_solution_sections(item: ThreadIndexItem, category: str) -> Dict[str, List[str]]:
    file_path = normalize_file_path(item.file_path)

    if category == ThreadCategory.DIRECT_CLOSE:
        return {
            "initial": [
                "[AGENT_REQUIRED] Confirm why this thread is obsolete/outdated in current codebase.",
                f"[AGENT_REQUIRED] Point to replacement path/symbol for `{file_path}`.",
            ],
            "planned": [
                "[AGENT_REQUIRED] Add exact close rationale to PR thread reply (1-2 sentences).",
                "[AGENT_REQUIRED] If any follow-up work remains, list concrete file-level actions.",
                "Mark this thread as resolved in local checklists after reply is prepared.",
            ],
            "validation": [
                "[AGENT_REQUIRED] Verify rationale references current files/functions and is reviewer-readable.",
                "Confirm checklist status is consistent in both files.",
            ],
        }

    if category == ThreadCategory.NEED_DIRECTION:
        return {
            "initial": [
                "[AGENT_REQUIRED] Write the decision question in one precise sentence.",
                "[AGENT_REQUIRED] Summarize two options with trade-offs in this PR context.",
            ],
            "planned": [
                "[AGENT_REQUIRED] Add required maintainer decision and owner (who decides).",
                "[AGENT_REQUIRED] State exact code/docs changes after decision (file paths + key edits).",
                "Mark checklist state only after decision is captured.",
            ],
            "validation": [
                "[AGENT_REQUIRED] Link decision evidence in PR thread or meeting note.",
                "[AGENT_REQUIRED] Ensure implementation matches final decision exactly.",
            ],
        }

    return {
        "initial": [
            "[AGENT_REQUIRED] Summarize the root issue in one sentence using reviewer comment + current code context.",
            f"[AGENT_REQUIRED] State intended end state in `{file_path}` (what should be true after fix).",
        ],
        "planned": [
            "[AGENT_REQUIRED] List exact file edits (path + symbol/function + expected change).",
            "[AGENT_REQUIRED] Include exact user-visible/behavioral impact.",
            "[AGENT_REQUIRED] List concrete verification commands (lint/test/docs build) and expected result.",
        ],
        "validation": [
            "[AGENT_REQUIRED] Define objective acceptance criteria tied to this thread.",
            "[AGENT_REQUIRED] Confirm no regression scope and how it is checked.",
        ],
    }


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)

    pr_number = resolve_pr_number(args.pr_number)
    pr_dir = REPO_ROOT / ".pr" / str(pr_number)

    input_path = args.input or (pr_dir / "unresolved_checklist.md")
    output_path = args.output or (pr_dir / "unresolved_solutions.md")

    if not input_path.exists():
        raise RuntimeError(f"Input checklist not found: {input_path}")
    if output_path.exists() and not args.overwrite:
        raise RuntimeError(f"Output already exists: {output_path}. Use --overwrite to replace.")
    if args.reset_all and not args.overwrite:
        raise RuntimeError("--reset-all requires --overwrite.")

    preserved_map: Dict[str, PreservedProposal] = {}
    preserve_existing = output_path.exists() and args.overwrite and not args.reset_all
    if preserve_existing:
        existing_content = output_path.read_text(encoding="utf-8", errors="replace")
        preserved_map = parse_preserved_proposals(existing_content)

    content = input_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    section_map = parse_thread_sections(content)
    items = parse_index_items(lines, section_map)
    direct_close_ids = set(args.direct_close_thread_ids or [])
    decision_ids = set(args.decision_thread_ids or [])
    invalid_ids = {
        thread_id
        for thread_id in (direct_close_ids | decision_ids)
        if not re.match(r"^TH-\d+$", thread_id)
    }
    if invalid_ids:
        raise RuntimeError(f"Invalid thread IDs: {', '.join(sorted(invalid_ids))}")

    rendered = render_output_with_categories(
        pr_number,
        items,
        input_path,
        direct_close_ids=direct_close_ids,
        decision_ids=decision_ids,
        preserved_map=preserved_map,
        preserve_existing=preserve_existing,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    unresolved_count = len([item for item in items if not item.checked])
    reused_count = len(
        {
            item.thread_id
            for item in items
            if not item.checked and item.thread_id in preserved_map
        }
    )
    LOGGER.info(
        "Generated %s with %d unresolved entries (preserved=%d, reset_all=%s).",
        output_path,
        unresolved_count,
        reused_count,
        args.reset_all,
    )
    return 0


def render_output_with_categories(
    pr_number: int,
    items: List[ThreadIndexItem],
    source_path: Path,
    direct_close_ids: Set[str],
    decision_ids: Set[str],
    preserved_map: Dict[str, PreservedProposal],
    preserve_existing: bool,
) -> str:
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    unresolved_items = [item for item in items if not item.checked]
    reviewer_counts: Dict[str, int] = {}
    for item in unresolved_items:
        reviewer_counts[item.reviewer] = reviewer_counts.get(item.reviewer, 0) + 1

    lines: List[str] = []
    lines.append(f"# PR #{pr_number} Unresolved Solutions (Draft)")
    lines.append("")
    lines.append(f"- Source: `{source_path}`")
    lines.append(f"- Generated at (UTC): {now_utc}")
    lines.append(f"- Total unresolved threads: {len(unresolved_items)}")
    if preserve_existing:
        lines.append(
            "- Generation mode: preserve-existing (existing thread proposals are kept; new threads are scaffold-only)"
        )
    else:
        lines.append("- Generation mode: scaffold-only (agent must fill all `AGENT_REQUIRED` items)")
    if reviewer_counts:
        reviewer_summary = ", ".join(
            f"{reviewer}={count}" for reviewer, count in sorted(reviewer_counts.items())
        )
        lines.append(f"- Reviewer breakdown: {reviewer_summary}")

    category_map = classify_threads(
        unresolved_items,
        direct_close_ids=direct_close_ids,
        decision_ids=decision_ids,
    )
    direct_close_count = sum(
        1 for thread_id in category_map if category_map[thread_id] == ThreadCategory.DIRECT_CLOSE
    )
    need_direction_count = sum(
        1 for thread_id in category_map if category_map[thread_id] == ThreadCategory.NEED_DIRECTION
    )
    code_doc_change_count = len(unresolved_items) - direct_close_count - need_direction_count

    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"- <span style=\"color:#d32f2f;\"><strong>建议直接关闭（已被后续重构覆盖）: {direct_close_count}</strong></span>"
    )
    lines.append(f"- `建议改动代码/文档`: {code_doc_change_count}")
    lines.append(f"- `建议先定方向再改（产品/规范决策）`: {need_direction_count}")
    lines.append(
        "- 标记说明: <span style=\"color:#d32f2f;\"><strong>红色标签 = 建议直接关闭</strong></span>"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Thread Proposals")
    lines.append("")

    for item in unresolved_items:
        category = category_map[item.thread_id]
        category_label = format_category_label(category)
        default_handling_label = format_handling_label(category)
        default_section = build_solution_sections(item, category)
        preserved = preserved_map.get(item.thread_id)
        section = default_section
        handling_label = default_handling_label
        status_label = "`draft-needs-agent-input`"
        if preserved is not None:
            section = {
                "initial": preserved.initial or default_section["initial"],
                "planned": preserved.planned or default_section["planned"],
                "validation": preserved.validation or default_section["validation"],
            }
            handling_label = preserved.handling_label or default_handling_label
            status_label = preserved.status_label or status_label

        lines.append(f"### {item.thread_id}")
        lines.append(f"- Reviewer: `{item.reviewer}`")
        lines.append(f"- 分类标记: {category_label}")
        lines.append(f"- File: `{item.file_path}`")
        lines.append(f"- Outdated: `{'yes' if item.outdated else 'no'}`")
        lines.append(f"- Thread: {item.thread_url if item.thread_url else 'N/A'}")
        lines.append(f"- Review Comment Excerpt: {item.comment_excerpt}")
        lines.append("- Initial Solution Proposal:")
        for entry in section["initial"]:
            lines.append(f"  - {entry}")
        lines.append("- Planned Changes:")
        for entry in section["planned"]:
            lines.append(f"  - {entry}")
        lines.append("- Validation:")
        for entry in section["validation"]:
            lines.append(f"  - {entry}")
        lines.append(f"- 建议处理: {handling_label}")
        lines.append(f"- Status: {status_label}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
