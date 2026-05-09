from __future__ import annotations

import argparse
from typing import Any, Dict, Optional

from browseruse_bench.utils import handle_cli_errors


def configure_viz_parser(parser: argparse.ArgumentParser, _config: Dict[str, Any] | None = None) -> None:
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1; use 0.0.0.0 to expose to the network)",
    )
    parser.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    parser.add_argument("--watch", action="store_true", help="Auto-regenerate index on file changes")
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=3.0,
        help="Watch poll interval in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="Generate experiments.json and exit without starting the server",
    )


def viz_command(args: argparse.Namespace, _config: Dict[str, Any]) -> int:
    from browseruse_bench.visualization.serve import run_server

    return run_server(
        host=args.host,
        port=args.port,
        watch=args.watch,
        watch_interval=args.watch_interval,
        generate_only=args.generate_only,
    )


@handle_cli_errors
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="bubench viz")
    configure_viz_parser(parser)
    args = parser.parse_args(argv)
    setattr(args, "extra_args", [])
    return viz_command(args, {})


if __name__ == "__main__":
    raise SystemExit(main())
