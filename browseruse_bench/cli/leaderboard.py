from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional

from browseruse_bench.leaderboard.generator import main as leaderboard_main
from browseruse_bench.utils import handle_cli_errors, setup_logger

# Setup logger
logger = setup_logger("leaderboard")


def configure_leaderboard_parser(parser: argparse.ArgumentParser, _config: Dict[str, Any] | None = None) -> None:
    """Configure arguments for the leaderboard command."""
    parser.add_argument("--output-name", default="leaderboard.html", help="Output filename")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: experiments/)")


def _build_argv(args: argparse.Namespace, extra_args: List[str]) -> List[str]:
    cmd: List[str] = []
    if args.output_name:
        cmd.extend(["--output-name", args.output_name])
    if args.output_dir:
        cmd.extend(["--output-dir", str(args.output_dir)])
    cmd.extend(extra_args)
    return cmd


def leaderboard_command(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Entry point for the leaderboard subcommand."""
    extra_args = getattr(args, "extra_args", [])
    argv = _build_argv(args, extra_args)
    return leaderboard_main(argv)


@handle_cli_errors
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="bubench leaderboard")
    configure_leaderboard_parser(parser)
    args, extra = parser.parse_known_args(argv)
    if extra:
        logger.info("Forwarding extra arguments: %s", " ".join(extra))
    setattr(args, "extra_args", extra)
    return leaderboard_command(args, {})


if __name__ == "__main__":
    raise SystemExit(main())
