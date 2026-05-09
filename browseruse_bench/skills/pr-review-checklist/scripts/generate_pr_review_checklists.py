from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from browseruse_bench.utils import REPO_ROOT


LOGGER = logging.getLogger(__name__)

REVIEW_THREADS_QUERY = (
    "query($owner:String!, $repo:String!, $number:Int!, $after:String) { "
    "repository(owner:$owner,name:$repo){ "
    "pullRequest(number:$number){ "
    "reviewThreads(first:100, after:$after){ "
    "nodes{ "
    "isResolved isOutdated path line originalLine "
    "comments(first:20){ "
    "nodes{ databaseId author{login} body createdAt url replyTo{databaseId} } "
    "} "
    "} "
    "pageInfo{hasNextPage endCursor} "
    "} "
    "} "
    "} "
    "}"
)

CHECKBOX_PATTERN = re.compile(r"^- \[(?P<state>[ xX])\] (?P<thread_id>TH-\d+) \|")


@dataclass(frozen=True)
class ReviewComment:
    comment_id: int
    author: str
    body: str
    created_at: str
    url: str
    reply_to_id: Optional[int]


@dataclass(frozen=True)
class ReviewThread:
    path: str
    line: int
    is_resolved: bool
    is_outdated: bool
    comments: List[ReviewComment]


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
        raise RuntimeError(
            f"Command not found: {command[0]}. Please install it and retry."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or "No command output"
        raise RuntimeError(
            f"Command failed ({' '.join(command)}): {detail}"
        ) from exc
    return result.stdout


def run_gh_json(args: Sequence[str]) -> Any:
    raw_output = run_command(["gh", *args])
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to decode JSON from gh {' '.join(args)}") from exc


def ensure_gh_auth() -> None:
    try:
        run_command(["gh", "auth", "status"])
    except RuntimeError as exc:
        raise RuntimeError(
            "GitHub CLI authentication required. Run `gh auth login` and ensure access to the target repository."
        ) from exc


def parse_repo_slug_from_remote(remote_url: str) -> str:
    ssh_match = re.match(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", remote_url)
    if ssh_match:
        return f"{ssh_match.group('owner')}/{ssh_match.group('repo')}"

    https_match = re.match(
        r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        remote_url,
    )
    if https_match:
        return f"{https_match.group('owner')}/{https_match.group('repo')}"

    raise ValueError(f"Unsupported GitHub remote URL format: {remote_url}")


def resolve_repo_slug(repo_arg: Optional[str]) -> str:
    if repo_arg:
        if "/" not in repo_arg:
            raise ValueError(f"Invalid repo slug: {repo_arg}")
        return repo_arg

    remote_url = run_command(["git", "remote", "get-url", "origin"]).strip()
    if not remote_url:
        raise RuntimeError("Could not resolve git remote origin URL")
    return parse_repo_slug_from_remote(remote_url)


def resolve_pr_number(repo_slug: str, pr_number_arg: Optional[int]) -> int:
    if pr_number_arg is not None:
        return pr_number_arg

    try:
        current_pr = run_command(
            ["gh", "pr", "view", "--repo", repo_slug, "--json", "number", "--jq", ".number"]
        ).strip()
        if current_pr:
            return int(current_pr)
    except (RuntimeError, ValueError):
        LOGGER.info("Current branch PR view failed; fallback to PR list by head branch")

    current_branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not current_branch:
        raise RuntimeError("Could not resolve current git branch")

    pr_candidates = run_gh_json(
        [
            "pr",
            "list",
            "--repo",
            repo_slug,
            "--head",
            current_branch,
            "--state",
            "all",
            "--json",
            "number,updatedAt",
            "--limit",
            "20",
        ]
    )

    if not isinstance(pr_candidates, list) or not pr_candidates:
        raise RuntimeError(
            f"No PR found for branch '{current_branch}'. Pass --pr-number explicitly."
        )

    latest_candidate = max(
        pr_candidates,
        key=lambda item: str(item.get("updatedAt", "")),
    )
    try:
        return int(latest_candidate["number"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Failed to parse PR number from gh pr list output") from exc


def parse_review_comment(raw: Dict[str, Any]) -> ReviewComment:
    reply_to_raw = raw.get("replyTo")
    reply_to_id: Optional[int] = None
    if isinstance(reply_to_raw, dict) and reply_to_raw.get("databaseId") is not None:
        reply_to_id = int(reply_to_raw["databaseId"])

    return ReviewComment(
        comment_id=int(raw["databaseId"]),
        author=str(raw["author"]["login"]),
        body=str(raw.get("body", "")),
        created_at=str(raw.get("createdAt", "")),
        url=str(raw.get("url", "")),
        reply_to_id=reply_to_id,
    )


def parse_review_thread(raw: Dict[str, Any]) -> ReviewThread:
    comments_raw = raw.get("comments", {}).get("nodes", [])
    comments = [parse_review_comment(comment) for comment in comments_raw]
    comments.sort(key=lambda item: item.created_at)
    line_value = int(raw.get("line") or raw.get("originalLine") or 0)

    return ReviewThread(
        path=str(raw.get("path", "")),
        line=line_value,
        is_resolved=bool(raw.get("isResolved", False)),
        is_outdated=bool(raw.get("isOutdated", False)),
        comments=comments,
    )


def fetch_review_threads(repo_slug: str, pr_number: int) -> List[ReviewThread]:
    owner, repo = repo_slug.split("/", maxsplit=1)
    nodes: List[Dict[str, Any]] = []
    after_cursor: Optional[str] = None

    while True:
        command = [
            "api",
            "graphql",
            "-f",
            f"query={REVIEW_THREADS_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"repo={repo}",
            "-F",
            f"number={pr_number}",
        ]
        if after_cursor:
            command.extend(["-f", f"after={after_cursor}"])

        payload = run_gh_json(command)

        try:
            review_threads_obj = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
            page_nodes = review_threads_obj["nodes"]
            page_info = review_threads_obj["pageInfo"]
            has_next_page = bool(page_info["hasNextPage"])
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                "Unexpected GraphQL payload while loading review threads"
            ) from exc

        nodes.extend(page_nodes)
        if not has_next_page:
            break

        end_cursor = page_info.get("endCursor")
        if not isinstance(end_cursor, str) or not end_cursor:
            raise RuntimeError(
                "GraphQL pagination indicated more pages but endCursor was missing"
            )
        after_cursor = end_cursor

    parsed_threads = [parse_review_thread(item) for item in nodes]
    parsed_threads = [thread for thread in parsed_threads if thread.comments]
    parsed_threads.sort(key=lambda thread: thread.comments[0].created_at)
    return parsed_threads


def fetch_pr_comment_map(repo_slug: str, pr_number: int) -> Dict[int, Dict[str, Any]]:
    items = run_gh_json(["api", "--paginate", f"repos/{repo_slug}/pulls/{pr_number}/comments"])
    if not isinstance(items, list):
        raise RuntimeError("Unexpected response from pull comments API")

    comment_map: Dict[int, Dict[str, Any]] = {}
    for item in items:
        comment_id_raw = item.get("id")
        if comment_id_raw is None:
            continue
        comment_map[int(comment_id_raw)] = item
    return comment_map


def get_root_comment(thread: ReviewThread) -> ReviewComment:
    root_candidates = [comment for comment in thread.comments if comment.reply_to_id is None]
    if root_candidates:
        return root_candidates[0]
    return thread.comments[0]


def build_diff_hunk(thread: ReviewThread, comment_map: Dict[int, Dict[str, Any]]) -> str:
    root_comment = get_root_comment(thread)
    root_item = comment_map.get(root_comment.comment_id)
    if not root_item:
        return "[diff hunk unavailable: comment id not found in pull comments API]"

    diff_hunk = root_item.get("diff_hunk")
    if not diff_hunk:
        return "[diff hunk unavailable for this comment]"
    return str(diff_hunk).rstrip("\n")


def build_current_context(path: str, line: int, radius: int) -> str:
    absolute_path = REPO_ROOT / path
    if not absolute_path.exists():
        return f"[file not found] {absolute_path}"

    try:
        content = absolute_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[failed to read file] {absolute_path}: {exc}"

    lines = content.splitlines()
    if not lines:
        return "[empty file]"

    if line <= 0:
        start = 1
        end = min(len(lines), 12)
        target_line = 0
    else:
        target_line = min(line, len(lines))
        start = max(1, target_line - radius)
        end = min(len(lines), target_line + radius)

    rendered: List[str] = []
    for current_line in range(start, end + 1):
        marker = ">" if current_line == target_line and target_line > 0 else " "
        rendered.append(f"{current_line:5d}{marker} {lines[current_line - 1]}")
    return "\n".join(rendered)


def thread_key(thread: ReviewThread) -> str:
    root = get_root_comment(thread)
    return f"TH-{root.comment_id}"


def load_existing_checks(unresolved_path: Path) -> Dict[str, bool]:
    if not unresolved_path.exists():
        return {}

    try:
        lines = unresolved_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}

    states: Dict[str, bool] = {}
    for line in lines:
        match = CHECKBOX_PATTERN.match(line)
        if not match:
            continue
        states[match.group("thread_id")] = match.group("state").lower() == "x"
    return states


def render_index_line(
    key: str,
    thread: ReviewThread,
    checked: bool,
    include_resolved_tag: bool,
) -> str:
    checkbox = "x" if checked else " "
    root = get_root_comment(thread)
    absolute_path = REPO_ROOT / thread.path

    parts: List[str] = [
        f"- [{checkbox}] {key}",
        f"`{absolute_path}:{thread.line}`",
    ]
    if include_resolved_tag:
        parts.append("resolved" if thread.is_resolved else "unresolved")
    if thread.is_outdated:
        parts.append("outdated")
    parts.append(f"root={root.author}")
    parts.append(f"[thread]({root.url})")
    return " | ".join(parts)


def render_thread_block(
    key: str,
    thread: ReviewThread,
    comment_map: Dict[int, Dict[str, Any]],
    context_radius: int,
) -> List[str]:
    root = get_root_comment(thread)
    absolute_path = REPO_ROOT / thread.path
    block: List[str] = [
        f"### {key}",
        f"- File: `{absolute_path}:{thread.line}`",
        f"- Resolved: {'yes' if thread.is_resolved else 'no'}",
        f"- Outdated: {'yes' if thread.is_outdated else 'no'}",
        f"- Comment count: {len(thread.comments)}",
        "",
        "Code Snippet (PR diff hunk):",
        "",
        "```diff",
        build_diff_hunk(thread, comment_map),
        "```",
        "",
        "Current File Context (near commented line):",
        "",
        "```text",
        build_current_context(thread.path, thread.line, context_radius),
        "```",
        "",
        "Raw chat log:",
        "",
    ]

    for comment in thread.comments:
        reply_suffix = f" | reply_to={comment.reply_to_id}" if comment.reply_to_id is not None else ""
        body = comment.body if comment.body else "[empty comment body]"
        block.extend(
            [
                f"- {comment.author} | {comment.created_at}{reply_suffix}",
                "",
                "````text",
                body,
                "````",
                "",
            ]
        )

    return block


def render_markdown(
    repo_slug: str,
    pr_number: int,
    threads: List[ReviewThread],
    comment_map: Dict[int, Dict[str, Any]],
    context_radius: int,
    checked_map: Dict[str, bool],
    unresolved_only: bool,
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    selected_threads = [thread for thread in threads if (not unresolved_only or not thread.is_resolved)]

    if unresolved_only:
        title = "# PR Review Unresolved Checklist (with code snippets)"
    else:
        title = "# PR Review Checklist (with code snippets)"

    lines: List[str] = [
        title,
        "",
        f"- Generated at (UTC): {generated_at}",
        f"- Repo: {repo_slug}",
        f"- PR: https://github.com/{repo_slug}/pull/{pr_number}",
        "- Note: `Current File Context` is based on current workspace files and may differ from PR-time code for outdated threads.",
        "",
        "## Index",
    ]

    for thread in selected_threads:
        key = thread_key(thread)
        checked = checked_map.get(key, False) if unresolved_only else False
        lines.append(
            render_index_line(
                key=key,
                thread=thread,
                checked=checked,
                include_resolved_tag=not unresolved_only,
            )
        )

    lines.extend(["", "## Threads"])

    for thread in selected_threads:
        key = thread_key(thread)
        lines.extend(render_thread_block(key, thread, comment_map, context_radius))

    return "\n".join(lines).rstrip() + "\n"


def write_checklists(
    repo_slug: str,
    pr_number: int,
    threads: List[ReviewThread],
    comment_map: Dict[int, Dict[str, Any]],
    context_radius: int,
) -> Tuple[Path, Path]:
    output_dir = REPO_ROOT / ".pr" / str(pr_number)
    output_dir.mkdir(parents=True, exist_ok=True)

    review_path = output_dir / "review_checklist.md"
    unresolved_path = output_dir / "unresolved_checklist.md"

    checked_map = load_existing_checks(unresolved_path)

    review_markdown = render_markdown(
        repo_slug=repo_slug,
        pr_number=pr_number,
        threads=threads,
        comment_map=comment_map,
        context_radius=context_radius,
        checked_map={},
        unresolved_only=False,
    )
    unresolved_markdown = render_markdown(
        repo_slug=repo_slug,
        pr_number=pr_number,
        threads=threads,
        comment_map=comment_map,
        context_radius=context_radius,
        checked_map=checked_map,
        unresolved_only=True,
    )

    review_path.write_text(review_markdown, encoding="utf-8")
    unresolved_path.write_text(unresolved_markdown, encoding="utf-8")

    return review_path, unresolved_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate PR review checklists with code snippets in .pr/<pr_number>/"
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="GitHub repo slug (owner/repo). Defaults to origin remote.",
    )
    parser.add_argument(
        "--pr-number",
        type=int,
        default=None,
        help="PR number. Defaults to current branch PR.",
    )
    parser.add_argument(
        "--context-radius",
        type=int,
        default=4,
        help="Lines before and after commented line for current file context.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    if args.context_radius < 0:
        raise ValueError("--context-radius must be >= 0")

    ensure_gh_auth()

    repo_slug = resolve_repo_slug(args.repo)
    pr_number = resolve_pr_number(repo_slug, args.pr_number)

    LOGGER.info("Loading review data for %s PR #%s", repo_slug, pr_number)
    threads = fetch_review_threads(repo_slug, pr_number)
    comment_map = fetch_pr_comment_map(repo_slug, pr_number)

    review_path, unresolved_path = write_checklists(
        repo_slug=repo_slug,
        pr_number=pr_number,
        threads=threads,
        comment_map=comment_map,
        context_radius=args.context_radius,
    )

    unresolved_count = len([thread for thread in threads if not thread.is_resolved])
    LOGGER.info("Review checklist written: %s", review_path)
    LOGGER.info("Unresolved checklist written: %s", unresolved_path)
    LOGGER.info("Threads total=%s unresolved=%s", len(threads), unresolved_count)


if __name__ == "__main__":
    main()
