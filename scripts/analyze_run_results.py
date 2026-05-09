#!/usr/bin/env python3
"""Analyze task run results, including success/failure cause analysis"""

import json
import logging
import sys
from collections import Counter, defaultdict

from browseruse_bench.utils import REPO_ROOT, setup_logger

logger = logging.getLogger(__name__)


def analyze_task_result(task_id, result_path, task_info):
    """Analyze result of a single task"""
    with open(result_path, 'r', encoding='utf-8') as f:
        result = json.load(f)

    analysis = {
        'task_id': task_id,
        'website': task_info.get('target_website', 'unknown'),
        'query': task_info.get('query', ''),
        'task_type': task_info.get('task_type', ''),
        'login_type': task_info.get('login_type', ''),
        'domain': task_info.get('domain', ''),
    }

    # Determine status
    has_error = 'error' in result
    answer = result.get('answer', '')

    if has_error:
        analysis['status'] = 'error'
        analysis['error_message'] = result['error']
    elif 'failed' in str(answer).lower():
        analysis['status'] = 'failed'
        analysis['error_message'] = answer
    else:
        analysis['status'] = 'success'
        analysis['answer'] = answer

    # Execution metrics
    metrics = result.get('metrics', {})
    analysis['steps'] = metrics.get('steps', 0)
    analysis['time_ms'] = metrics.get('end_to_end_ms', 0)
    analysis['tokens'] = metrics.get('usage', {}).get('total_tokens', 0)
    analysis['cost'] = metrics.get('usage', {}).get('total_cost', 0)

    # Screenshot count
    trajectory_dir = result_path.parent / 'trajectory'
    screenshot_count = len(list(trajectory_dir.glob('screenshot-*.png'))) if trajectory_dir.exists() else 0
    analysis['screenshot_count'] = screenshot_count

    # Analyze failure cause
    if analysis['status'] in ['error', 'failed']:
        action_history = result.get('action_history', [])

        # Check if it is a login issue
        if screenshot_count == 0 and len(action_history) == 0:
            analysis['failure_cause'] = 'login_blocked'
            analysis['failure_description'] = 'Browser failed to start or blocked by login page'
        elif 'Timeout' in str(result.get('error', '')):
            if screenshot_count <= 2:
                analysis['failure_cause'] = 'login_timeout'
                analysis['failure_description'] = 'Likely stuck on login verification page'
            elif screenshot_count > 50:
                analysis['failure_cause'] = 'agent_loop'
                analysis['failure_description'] = 'Agent trapped in repetitive action loop'
            else:
                analysis['failure_cause'] = 'task_timeout'
                analysis['failure_description'] = 'High task complexity, execution timed out'
        else:
            analysis['failure_cause'] = 'execution_error'
            analysis['failure_description'] = result.get('error', 'Unknown Error')

    return analysis


def main():
    setup_logger("analyze-run-results")
    if len(sys.argv) < 2:
        logger.error("Usage: python analyze_run_results.py <timestamp>")
        logger.error("Example: python analyze_run_results.py 20260113_141214")
        sys.exit(1)

    timestamp = sys.argv[1]

    # Path settings
    result_dir = REPO_ROOT / 'experiments' / 'LexBench-Browser' / '20260120' / 'high_freq_login' / 'browser-use' / timestamp / 'tasks'
    dataset_file = REPO_ROOT / 'browseruse_bench' / 'data' / 'LexBench-Browser' / 'task.jsonl'

    if not result_dir.exists():
        logger.error(f"[FAILED] Result directory does not exist: {result_dir}")
        sys.exit(1)

    # Read dataset (supports JSON object and JSONL)
    with open(dataset_file, 'r', encoding='utf-8') as f:
        raw_text = f.read()
    try:
        dataset = json.loads(raw_text)
        tasks = dataset['tasks']
    except json.JSONDecodeError:
        tasks = []
        for line in raw_text.splitlines():
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    task_map = {str(task['id']): task for task in tasks}

    # Analyze all tasks
    task_dirs = sorted([d for d in result_dir.iterdir() if d.is_dir()],
                      key=lambda x: int(x.name))

    results = []
    for task_dir in task_dirs:
        task_id = task_dir.name
        result_path = task_dir / 'result.json'
        if result_path.exists() and task_id in task_map:
            analysis = analyze_task_result(task_id, result_path, task_map[task_id])
            results.append(analysis)

    # Generate report
    logger.info('\n' + '='*100)
    logger.info(' '*35 + 'Task Execution Analysis Report')
    logger.info('='*100)
    logger.info(f'Run Timestamp: {timestamp}')
    logger.info(f'Total Tasks: {len(results)}')

    # Statistics
    status_counts = Counter([r['status'] for r in results])
    success_count = status_counts.get('success', 0)
    total_count = len(results)
    success_rate = success_count / total_count * 100 if total_count > 0 else 0

    logger.info('[STATS] Overall Statistics')
    logger.info('-'*100)
    logger.info(f'  [SUCCESS] SUCCESS: {success_count} ({success_rate:.1f}%)')
    logger.info(f'  [FAILED] Failed: {status_counts.get("failed", 0)}')
    logger.info(f'  [ERROR] Error: {status_counts.get("error", 0)}')

    # Stats by website
    website_stats = defaultdict(lambda: {'total': 0, 'success': 0, 'failed': 0, 'error': 0})
    for r in results:
        website = r['website']
        website_stats[website]['total'] += 1
        website_stats[website][r['status']] += 1

    logger.info('[STATS] Execution by Website')
    logger.info('-'*100)
    logger.info(f'{"Website":<35} {"SUCCESS/TOTAL":<15} {"Rate":<10} {"Avg Steps":<10} {"Avg Time"}')
    logger.info('-'*100)

    for website in sorted(website_stats.keys(), key=lambda x: website_stats[x]['total'], reverse=True):
        stats = website_stats[website]
        success = stats['success']
        total = stats['total']
        rate = success / total * 100 if total > 0 else 0

        # Calculate average steps and time
        website_results = [r for r in results if r['website'] == website]
        success_results = [r for r in website_results if r['status'] == 'success']

        if success_results:
            avg_steps = sum(r['steps'] for r in success_results) / len(success_results)
            avg_time = sum(r['time_ms'] for r in success_results) / len(success_results) / 1000
            logger.info(
                f'{website:<35} {success:2d}/{total:2d} ({rate:5.1f}%)   '
                f'{avg_steps:6.1f}steps   {avg_time:6.1f}s'
            )
        else:
            logger.info(f'{website:<35} {success:2d}/{total:2d} ({rate:5.1f}%)   {"N/A":<10} {"N/A"}')

    # Success task details
    success_results = [r for r in results if r['status'] == 'success']
    if success_results:
        logger.info(f'\n[SUCCESS] SUCCESS Task Details ({len(success_results)})')
        logger.info('='*100)

        # Group by website
        success_by_website = defaultdict(list)
        for r in success_results:
            success_by_website[r['website']].append(r)

        for website in sorted(success_by_website.keys()):
            tasks_list = success_by_website[website]
            logger.info(f'\n[{website}]- {len(tasks_list)} SUCCESS')
            logger.info('-'*100)
            for r in sorted(tasks_list, key=lambda x: int(x['task_id'])):
                logger.info(
                    f'  Task {r["task_id"]:3s} | {r["steps"]:2d}steps | '
                    f'{r["time_ms"]/1000:6.1f}s | {r["tokens"]:,}tokens | ${r["cost"]:.4f}'
                )
                query = r['query'][:70] + '...' if len(r['query']) > 70 else r['query']
                logger.info(f'           {query}')

    # Failed task details
    failed_results = [r for r in results if r['status'] in ['error', 'failed']]
    if failed_results:
        logger.info(f'\n[FAILED] Failed Task Details ({len(failed_results)})')
        logger.info('='*100)

        # Group by failure cause
        failure_causes = Counter([r.get('failure_cause', 'unknown') for r in failed_results])

        logger.info('Failure Cause Distribution:')
        for cause, count in failure_causes.most_common():
            pct = count / len(failed_results) * 100
            logger.info(f'  • {cause:20s} {count:2d} ({pct:5.1f}%)')

        # Previous grouping by cause
        failed_by_cause = defaultdict(list)
        for r in failed_results:
            cause = r.get('failure_cause', 'unknown')
            failed_by_cause[cause].append(r)

        for cause in sorted(failed_by_cause.keys()):
            tasks_list = failed_by_cause[cause]
            logger.info(f'\n[{cause}]- {len(tasks_list)} Tasks')
            logger.info('-'*100)

            # Group by website
            by_website = defaultdict(list)
            for r in tasks_list:
                by_website[r['website']].append(r)

            for website, website_tasks in sorted(by_website.items()):
                logger.info(f'\n  {website}:')
                for r in sorted(website_tasks, key=lambda x: int(x['task_id'])):
                    logger.info(
                        f'    Task {r["task_id"]:3s} | Steps:{r["steps"]:2d} | '
                        f'Screenshots:{r["screenshot_count"]:2d} | {r.get("failure_description", "")}'
                    )
                    query = r['query'][:65] + '...' if len(r['query']) > 65 else r['query']
                    logger.info(f'             {query}')

    # Performance statistics
    success_results = [r for r in results if r['status'] == 'success']
    if success_results:
        total_tokens = sum(r['tokens'] for r in success_results)
        total_cost = sum(r['cost'] for r in success_results)
        total_time = sum(r['time_ms'] for r in success_results) / 1000

        logger.info(f'\n[COST] Cost Statistics ({len(success_results)} SUCCESS)')
        logger.info('='*100)
        logger.info(f'  Total Tokens: {total_tokens:,}')
        logger.info(f'  Total Cost: ${total_cost:.4f}')
        logger.info(f'  Total Time: {total_time:.1f}s ({total_time/60:.1f}min)')
        logger.info(
            f'  Avg per Task: {total_tokens/len(success_results):,.0f} tokens, '
            f'${total_cost/len(success_results):.4f}, {total_time/len(success_results):.1f}s'
        )

    # Suggestions
    logger.info('[NOTE] Suggestions')
    logger.info('='*100)

    if failed_results:
        login_failed = [r for r in failed_results if r.get('failure_cause') in ['login_blocked', 'login_timeout']]
        agent_failed = [r for r in failed_results if r.get('failure_cause') in ['agent_loop', 'task_timeout']]

        if login_failed:
            logger.info(f'\n[LOGIN] Login Issues ({len(login_failed)} tasks):')
            websites = set(r['website'] for r in login_failed)
            for website in sorted(websites):
                count = len([r for r in login_failed if r['website'] == website])
                logger.info(f'  • {website}: {count} failed')
                logger.info('    Suggestion: Relogin to this website in UC mode to ensure session validity')

        if agent_failed:
            logger.info(f'\n[AGENT] Agent Issues ({len(agent_failed)} tasks):')
            for r in agent_failed:
                logger.info(f'  • Task {r["task_id"]} ({r["website"]}): {r.get("failure_description")}')
                logger.info('    Suggestion: Optimize task strategy or increase timeout')

    if success_rate < 70:
        logger.warning(f'[WARNING] Low SUCCESS RATE ({success_rate:.1f}%)')
        logger.warning('  Suggestion: Check login status for all websites')
    elif success_rate >= 90:
        logger.info(f'[RESULT] Good performance! SUCCESS RATE reached {success_rate:.1f}%')

    logger.info('\n' + '='*100)

    # Save analysis results
    output_file = result_dir.parent / f'run_analysis_{timestamp}.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': timestamp,
            'summary': {
                'total': len(results),
                'success': success_count,
                'failed': status_counts.get('failed', 0),
                'error': status_counts.get('error', 0),
                'success_rate': success_rate,
            },
            'website_stats': dict(website_stats),
            'failure_causes': dict(failure_causes),
            'results': results
        }, f, ensure_ascii=False, indent=2)

    logger.info(f'Detailed analysis saved to: {output_file}')


if __name__ == '__main__':
    main()
