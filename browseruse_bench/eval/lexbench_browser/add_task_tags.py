#!/usr/bin/env python3
"""
Add login and risk control tags to tasks in tasks_with_solutions_total.json
"""

import json
import logging

from browseruse_bench.utils import setup_logger

logger = logging.getLogger(__name__)

# Define task IDs to tag and corresponding tags
TASK_TAGS = {
    # Login Required - Account Password
    "login_account_password": [1, 3, 11, 12, 13,14, 15, 16, 26, 47, 56, 61, 62, 71, 81, 101, 111, 113, 116, 126, 147, 156, 162, 203],

    # Login Required - SMS Code
    "login_phone_verification": [4],

    # Login Required - Captcha
    "login_captcha": [9],

    # Login Required - QR Code
    "login_qr_code": [2, 30, 130],

    # Risk Control - CAPTCHA
    "risk_control_captcha": [100, 126],

    # Risk Control - Slider
    "risk_control_slider_verification": [70, 170],

    # Risk Control - Anti-bot
    "risk_control_anti_bot": [14],

    # Risk Control - Rate Limiting
    "risk_control_rate_limiting": [81, 130],
}

def add_tags_to_tasks(input_file: str, output_file: str):
    """
    Add tags to tasks

    Args:
        input_file: Input JSON file path
        output_file: Output JSON file path
    """
    # Read JSON file
    with open(input_file, encoding='utf-8') as f:
        data = json.load(f)

    # Build task_id to tags mapping
    task_id_to_tags: dict[int, dict] = {}

    # Process login related tags
    for task_id in TASK_TAGS["login_account_password"]:
        if task_id not in task_id_to_tags:
            task_id_to_tags[task_id] = {}
        task_id_to_tags[task_id]["login_required"] = True
        task_id_to_tags[task_id]["login_type"] = "account_password"

    for task_id in TASK_TAGS["login_phone_verification"]:
        if task_id not in task_id_to_tags:
            task_id_to_tags[task_id] = {}
        task_id_to_tags[task_id]["login_required"] = True
        task_id_to_tags[task_id]["login_type"] = "phone_verification"

    for task_id in TASK_TAGS["login_captcha"]:
        if task_id not in task_id_to_tags:
            task_id_to_tags[task_id] = {}
        task_id_to_tags[task_id]["login_required"] = True
        task_id_to_tags[task_id]["login_type"] = "login_captcha"

    for task_id in TASK_TAGS["login_qr_code"]:
        if task_id not in task_id_to_tags:
            task_id_to_tags[task_id] = {}
        task_id_to_tags[task_id]["login_required"] = True
        task_id_to_tags[task_id]["login_type"] = "qr_code"

    # Process risk control related tags
    risk_control_types_map = {
        "risk_control_captcha": "captcha",
        "risk_control_slider_verification": "slider_verification",
        "risk_control_anti_bot": "anti_bot",
        "risk_control_rate_limiting": "rate_limiting",
    }

    for tag_key, risk_type in risk_control_types_map.items():
        for task_id in TASK_TAGS[tag_key]:
            if task_id not in task_id_to_tags:
                task_id_to_tags[task_id] = {}
            task_id_to_tags[task_id]["risk_control"] = True
            if "risk_control_types" not in task_id_to_tags[task_id]:
                task_id_to_tags[task_id]["risk_control_types"] = []
            task_id_to_tags[task_id]["risk_control_types"].append(risk_type)

    # Add tags to each task
    updated_count = 0
    total_tasks = len(data.get("tasks", []))
    logger.info(f"Total tasks to check: {total_tasks}")

    for idx, task in enumerate(data.get("tasks", []), 1):
        task_id = task.get("id")
        if task_id in task_id_to_tags:
            tags = task_id_to_tags[task_id]

            # Add or update login_required
            if "login_required" in tags:
                task["login_required"] = tags["login_required"]

            # Add login_type
            if "login_type" in tags:
                task["login_type"] = tags["login_type"]

            # Add risk_control
            if "risk_control" in tags:
                task["risk_control"] = tags["risk_control"]

            # Add risk_control_types
            if "risk_control_types" in tags:
                task["risk_control_types"] = tags["risk_control_types"]

            updated_count += 1
            logger.info(
                f"[{idx}/{total_tasks}] Updated Task {task_id}: "
                f"login_type={tags.get('login_type')}, "
                f"risk_control={tags.get('risk_control')}, "
                f"risk_control_types={tags.get('risk_control_types')}"
            )

    logger.info("Saving file...")
    # Save updated JSON file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Total tasks updated: {updated_count}")
    logger.info(f"Result saved to: {output_file}")

if __name__ == "__main__":
    setup_logger("lexbench-add-tags")
    import os
    import sys

    input_file = "benchmarks/LexBench-Browser/data/tasks_with_solutions_total.json"
    output_file = "benchmarks/LexBench-Browser/data/tasks_with_solutions_total.json"

    try:
        if not os.path.exists(input_file):
            logger.error(f"Error: File not found: {input_file}")
            sys.exit(1)

        logger.info(f"Processing file: {input_file}")
        add_tags_to_tasks(input_file, output_file)
    except Exception as e:
        logger.error(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
