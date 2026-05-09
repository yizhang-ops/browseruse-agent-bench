from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Callable

logger = logging.getLogger(__name__)


def handle_cli_errors(func: Callable[..., int]) -> Callable[..., None]:
    """CLI error handling decorator, handling exceptions and exit codes uniformly."""
    def wrapper(*args: Any, **kwargs: Any) -> None:
        try:
            sys.exit(func(*args, **kwargs))
        except KeyboardInterrupt:
            logger.warning("[WARNING] Interrupted")
            sys.exit(130)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, ImportError) as exc:
            logger.error("[FAILED] %s", exc)
            sys.exit(1)
    return wrapper


def _add_common_task_args(parser: argparse.ArgumentParser) -> None:
    """Add common task execution arguments."""
    parser.add_argument('--mode', choices=['single', 'first_n', 'specific', 'sample_n', 'by_id', 'all'],
                       default='all', help='Test mode (default: all)')
    parser.add_argument('--count', type=int, default=1,
                       help='Run first N tasks (mode=first_n) or sample N tasks (mode=sample_n) (default: 1)')
    parser.add_argument('--task-ids', nargs='+', type=str,
                       help='Specify task ID list (mode=specific)')
    parser.add_argument('--id', type=str,
                       help='Specify single task ID (mode=by_id)')
    parser.add_argument('--timeout', type=int,
                       help='Timeout per task (seconds)')
    parser.add_argument('--skip-completed', action='store_true',
                       help='Skip completed tasks')
    parser.add_argument('--dry-run', action='store_true', help='Show command only, do not execute')
    parser.add_argument('--region', choices=['zh', 'en'], default=None,
                       help='Filter tasks by website_region (zh=Chinese, en=English)')


def add_common_task_args(parser: argparse.ArgumentParser) -> None:
    """Add common task execution arguments to an existing parser."""
    _add_common_task_args(parser)


def create_run_parser() -> argparse.ArgumentParser:
    """Create argument parser for the main run script."""
    parser = argparse.ArgumentParser()
    _add_common_task_args(parser)
    return parser


def create_eval_parser() -> argparse.ArgumentParser:
    """Create argument parser for the evaluation script."""
    parser = argparse.ArgumentParser()
    _add_eval_args(parser)
    return parser


def _add_eval_args(parser: argparse.ArgumentParser) -> None:
    """Add evaluation arguments."""
    parser.add_argument("--mode", help="Evaluation mode")
    parser.add_argument("--model", help="Evaluation model")
    parser.add_argument(
        "--score-threshold",
        type=int,
        default=None,
        help="Score threshold (default: LexBench-Browser=60, others=3)",
    )
    parser.add_argument("--num-worker", type=int, default=1, help="Number of worker processes")
    parser.add_argument("--api-key", help="API Key")
    parser.add_argument("--base-url", help="API Base URL")
    parser.add_argument("--timestamp", help="Specific timestamp directory to evaluate (e.g. 20260120_225437)")
    parser.add_argument("--dry-run", action="store_true", help="Show command only, do not execute")
    parser.add_argument(
        "--eval-strategy",
        choices=["stepwise", "final"],
        default=None,
        help="Evaluation strategy (LexBench-Browser only; default: stepwise)",
    )


def add_eval_args(parser: argparse.ArgumentParser) -> None:
    """Add evaluation arguments to an existing parser."""
    _add_eval_args(parser)


def create_base_agent_parser(description: str, default_tasks_json: str, default_output_dir: str) -> argparse.ArgumentParser:
    """Create base argument parser for Agent run.py.

    Args:
        description: Description for the parser.
        default_tasks_json: Default tasks JSON file path.
        default_output_dir: Default output directory.

    Returns:
        argparse.ArgumentParser: Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--tasks-json', type=str, default=None,
                       help=f'Tasks JSON file path (default: {default_tasks_json})')
    parser.add_argument('--output-dir', type=str, default=default_output_dir,
                       help=f'Output directory (default: {default_output_dir})')
    parser.add_argument('--context-id', type=str, default=None,
                       help='Lexmount context ID to reuse saved login state (only works with lexmount browser)')
    _add_common_task_args(parser)
    # parser.set_defaults(timeout=300)  # Agent script defaults to 300 seconds
    return parser
