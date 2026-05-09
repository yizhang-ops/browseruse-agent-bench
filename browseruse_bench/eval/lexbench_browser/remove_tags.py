"""
Remove login_required field from all tasks
"""
import json
import logging
import os
import sys

from browseruse_bench.utils import setup_logger

logger = logging.getLogger(__name__)


def remove_login_required(file_path: str):
    """Remove login_required field from all tasks"""
    logger.info(f"Reading file: {file_path}")

    # Read file
    try:
        with open(file_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read file: {e}")
        return False

    tasks = data.get("tasks", [])
    logger.info(f"Found {len(tasks)} tasks")

    # Remove login_required field
    removed_count = 0
    for task in tasks:
        if "login_required" in task:
            del task["login_required"]
            removed_count += 1
            task_id = task.get("id", "Unknown")
            logger.info(f"  Task {task_id}: Removed login_required")

    logger.info(f"Total removed {removed_count} login_required fields")

    # Save file
    logger.info("Saving file...")
    try:
        # Backup original file
        backup_path = file_path + ".backup_before_remove"
        if not os.path.exists(backup_path):
            logger.info(f"Creating backup file: {backup_path}")
            with open(file_path, encoding='utf-8') as src, \
                 open(backup_path, 'w', encoding='utf-8') as dst:
                dst.write(src.read())

        # Save updated file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"File saved to: {file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save file: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    setup_logger("lexbench-remove-tags")
    file_path = "benchmarks/LexBench-Browser/data/tasks_with_solutions_total.json"

    if not os.path.exists(file_path):
        logger.error(f"Error: File not found: {file_path}")
        sys.exit(1)

    success = remove_login_required(file_path)
    sys.exit(0 if success else 1)
