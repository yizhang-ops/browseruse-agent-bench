from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional

from browseruse_bench.leaderboard.server import main as server_main
from browseruse_bench.utils import handle_cli_errors, setup_logger

# Setup logger
logger = setup_logger("server")


def configure_server_parser(parser: argparse.ArgumentParser, _config: Dict[str, Any] | None = None) -> None:
    """Configure arguments for the server command."""
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Server listen address (default: 0.0.0.0, allows external access)",
    )
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development mode)")


def _build_argv(args: argparse.Namespace, extra_args: List[str]) -> List[str]:
    cmd = ["--host", args.host, "--port", str(args.port)]
    if args.reload:
        cmd.append("--reload")
    cmd.extend(extra_args)
    return cmd


def server_command(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Entry point for the server subcommand."""
    extra_args = getattr(args, "extra_args", [])
    argv = _build_argv(args, extra_args)
    return server_main(argv)


@handle_cli_errors
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="bubench server")
    configure_server_parser(parser)
    args, extra = parser.parse_known_args(argv)
    if extra:
        logger.info("Forwarding extra arguments: %s", " ".join(extra))
    setattr(args, "extra_args", extra)
    return server_command(args, {})


if __name__ == "__main__":
    raise SystemExit(main())
