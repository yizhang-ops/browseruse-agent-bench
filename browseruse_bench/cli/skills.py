from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from browseruse_bench.utils import IS_WINDOWS, REPO_ROOT, handle_cli_errors, setup_logger

SKILLS_DIR = REPO_ROOT / "browseruse_bench" / "skills"
AGENT_SKILLS_MAP: Dict[str, Path] = {
    "antigravity": Path(".agent/skills"),
    "claude": Path(".claude/skills"),
    "codex": Path(".codex/skills"),
    "cursor": Path(".cursor/skills"),
}
DISPLAY_NAMES: Dict[str, str] = {
    "antigravity": "Antigravity",
    "claude": "Claude Code",
    "codex": "Codex",
    "cursor": "Cursor",
}
PREFERRED_OPTIONS: List[str] = ["claude", "codex", "cursor", "antigravity"]

# Setup logger
logger = setup_logger("skills", format_mode="plain")


def configure_skills_parser(parser: argparse.ArgumentParser, _config: Dict[str, Any] | None = None) -> None:
    """Configure arguments for the skills command."""
    parser.add_argument(
        "--agent",
        "-a",
        default="auto",
        help="Agent to install skills for (default: auto).",
    )
    parser.add_argument(
        "--auto",
        "-auto",
        action="store_true",
        help="Auto-detect the agent based on repo folders.",
    )
    parser.add_argument("--copy", action="store_true", help="Force copy instead of symlink.")
    parser.add_argument("--link", action="store_true", help="Prefer symlink instead of copy.")


def detect_candidates(repo_root: Path, agent_map: Dict[str, Path]) -> List[str]:
    candidates: List[str] = []
    seen_roots: Set[Path] = set()
    for name, skills_rel in agent_map.items():
        root_dir = (repo_root / skills_rel.parts[0]).resolve()
        if root_dir.exists():
            if root_dir in seen_roots:
                continue
            seen_roots.add(root_dir)
            candidates.append(name)

    return sorted(candidates)


def resolve_agent(agent: str) -> Tuple[Path, str]:
    if agent not in AGENT_SKILLS_MAP:
        raise ValueError(f"Unsupported agent: {agent}")
    return REPO_ROOT / AGENT_SKILLS_MAP[agent], agent


def parse_custom_destination(raw_value: str) -> Tuple[Path, str]:
    value = raw_value.strip()
    if not value:
        raise ValueError("Custom agent value cannot be empty.")

    if value in AGENT_SKILLS_MAP:
        return resolve_agent(value)

    has_sep = "/" in value or "\\" in value
    is_path = has_sep or value.startswith(".") or value.endswith("skills")

    if is_path:
        dest = Path(value).expanduser()
        if not dest.is_absolute():
            dest = REPO_ROOT / dest
        return dest, value

    dest = REPO_ROOT / f".{value}/skills"
    return dest, value


def prompt_for_agent(candidates: List[str]) -> Tuple[Path, str]:
    if not sys.stdin.isatty():
        raise ValueError("Auto-detection failed. Use --agent to specify one.")

    logger.info("Select an agent to install skills:")
    if candidates:
        logger.info("Detected agent folders: %s", ", ".join(candidates))
    else:
        logger.info("No agent folders detected.")

    options = [opt for opt in PREFERRED_OPTIONS if opt in AGENT_SKILLS_MAP]
    for index, name in enumerate(options, start=1):
        display = DISPLAY_NAMES.get(name, name)
        detected_tag = " (detected)" if name in candidates else ""
        logger.info("%s) %s%s", index, display, detected_tag)

    other_index = len(options) + 1
    logger.info("%s) Other (enter a custom agent name or path)", other_index)

    for _ in range(3):
        choice = input("Choose an option [1-{}] or type a name/path: ".format(other_index)).strip()
        if not choice:
            logger.info("Input cannot be empty.")
            continue

        if choice.isdigit():
            selected = int(choice)
            if 1 <= selected <= len(options):
                return resolve_agent(options[selected - 1])
            if selected == other_index:
                custom = input("Enter agent name or path: ").strip()
                return parse_custom_destination(custom)
            logger.info("Invalid selection: %s", choice)
            continue

        if choice in AGENT_SKILLS_MAP:
            return resolve_agent(choice)

        return parse_custom_destination(choice)

    raise ValueError("Too many invalid selections. Use --agent to specify one.")


def resolve_destination(args: argparse.Namespace) -> Tuple[Path, str]:
    agent = "auto" if args.auto else args.agent
    if agent != "auto":
        return resolve_agent(agent)

    candidates = detect_candidates(REPO_ROOT, AGENT_SKILLS_MAP)
    if len(candidates) == 1:
        return resolve_agent(candidates[0])

    return prompt_for_agent(candidates)


def prompt_for_link_mode() -> bool:
    if not sys.stdin.isatty():
        return not IS_WINDOWS

    default_mode = "copy" if IS_WINDOWS else "symlink"
    logger.info("Choose install mode:")
    logger.info("1) Symlink (recommended for macOS/Linux)")
    logger.info("2) Copy (recommended for Windows)")

    for _ in range(3):
        choice = input(
            "Install mode [1/2] (default: {}): ".format(default_mode)
        ).strip().lower()

        if not choice:
            return default_mode == "symlink"
        if choice in {"1", "symlink", "link"}:
            return True
        if choice in {"2", "copy"}:
            return False
        logger.info("Invalid selection: %s", choice)

    raise ValueError("Too many invalid selections. Use --copy or --link.")


def resolve_link_mode(args: argparse.Namespace) -> bool:
    if args.copy and args.link:
        raise ValueError("Use only one of --copy or --link.")
    if args.copy:
        return False
    if args.link:
        return True
    return prompt_for_link_mode()


def list_skill_dirs(skills_root: Path) -> List[Path]:
    if not skills_root.exists():
        raise FileNotFoundError(f"Skills directory not found: {skills_root}")

    skills = [entry for entry in skills_root.iterdir() if entry.is_dir()]
    if not skills:
        raise ValueError(f"No skill directories found in {skills_root}")

    return sorted(skills, key=lambda path: path.name)


def remove_existing(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return

    if path.exists():
        shutil.rmtree(path)


def try_symlink(source: Path, dest: Path) -> bool:
    if dest.is_symlink():
        try:
            if dest.resolve() == source.resolve():
                return True
        except FileNotFoundError:
            pass

    remove_existing(dest)

    try:
        os.symlink(source, dest, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        logger.info(
            "Symlink unavailable for %s (%s). Falling back to copy.",
            source.name,
            exc,
        )
        return False

    return True


def copy_dir(source: Path, dest: Path) -> None:
    remove_existing(dest)
    shutil.copytree(source, dest)


def install_skills(dest_root: Path, label: str, prefer_symlink: bool) -> None:
    skills = list_skill_dirs(SKILLS_DIR)
    dest_root.mkdir(parents=True, exist_ok=True)

    for skill in skills:
        dest_dir = dest_root / skill.name
        if prefer_symlink and try_symlink(skill, dest_dir):
            logger.info("Linked %s -> %s", skill.name, dest_dir)
            continue

        copy_dir(skill, dest_dir)
        logger.info("Copied %s -> %s", skill.name, dest_dir)

    logger.info("Install complete for: %s", label)


def skills_command(args: argparse.Namespace, _config: Dict[str, Any]) -> int:
    """Entry point for the skills subcommand."""
    extra_args = getattr(args, "extra_args", [])
    if extra_args:
        raise ValueError("Unknown arguments: {}".format(" ".join(extra_args)))

    try:
        dest_root, label = resolve_destination(args)
        prefer_symlink = resolve_link_mode(args)
        install_skills(dest_root, label, prefer_symlink=prefer_symlink)
    except (FileNotFoundError, ValueError, OSError, shutil.Error) as exc:
        logger.error("Install failed: %s", exc)
        return 1

    return 0


@handle_cli_errors
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="bubench skills")
    configure_skills_parser(parser)
    args, extra = parser.parse_known_args(argv)
    if extra:
        logger.debug("Forwarding extra arguments: %s", " ".join(extra))
    setattr(args, "extra_args", extra)
    return skills_command(args, {})


if __name__ == "__main__":
    raise SystemExit(main())
