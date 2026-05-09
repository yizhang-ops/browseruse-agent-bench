"""
AgentTARSAgent - Browser automation using the Agent-TARS CLI.

This agent executes tasks via the `agent-tars` command line tool.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import logging
import os
import re
import ssl
import struct
import tempfile
import threading
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from browseruse_bench.agents.cli_agent import CLIAgent
from browseruse_bench.agents.registry import register_agent
from browseruse_bench.browsers import open_browser_session
from browseruse_bench.browsers.providers.local import warn_if_local_proxy_unsupported
from browseruse_bench.schemas import AgentMetrics, AgentResult, AgentUsage
from browseruse_bench.utils import (
    IS_WINDOWS,
    decode_base64_to_file,
    extract_base64_from_content_item,
    find_key_recursive,
    load_json_records,
    safe_int,
    strip_base64_prefix,
)

logger = logging.getLogger(__name__)

# ── CDP screenshot helpers (stdlib-only, no playwright/websockets required) ──

_ITER_COMPLETE_RE = re.compile(r"LoopExecutor \[Iteration\] (\d+)/\d+ completed")
_CDP_SCREENSHOT_TIMEOUT = 12  # seconds per screenshot attempt


async def _ws_handshake(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    host: str,
    path: str,
) -> bool:
    key = base64.b64encode(os.urandom(16)).decode()
    writer.write(
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n".encode()
    )
    await writer.drain()
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = await reader.read(4096)
        if not chunk:
            return False
        buf += chunk
    return b"101" in buf


async def _ws_send(writer: asyncio.StreamWriter, text: str) -> None:
    data = text.encode()
    mask = os.urandom(4)
    length = len(data)
    if length < 126:
        header = struct.pack("BB", 0x81, 0x80 | length)
    elif length < 65536:
        header = struct.pack(">BBH", 0x81, 0xFE, length)
    else:
        header = struct.pack(">BBQ", 0x81, 0xFF, length)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    writer.write(header + mask + masked)
    await writer.drain()


async def _ws_recv(reader: asyncio.StreamReader) -> str:
    while True:
        header = await reader.readexactly(2)
        opcode = header[0] & 0x0F
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", await reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", await reader.readexactly(8))[0]
        payload = await reader.readexactly(length)
        # 0x8=close, 0x9=ping, 0xA=pong — skip control frames and read next
        if opcode in (0x8, 0x9, 0xA):
            continue
        return payload.decode(errors="replace")


async def _cdp_call(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    msg_id: int,
    method: str,
    params: dict[str, Any],
    session_id: str | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {"id": msg_id, "method": method, "params": params}
    if session_id:
        msg["sessionId"] = session_id
    await _ws_send(writer, json.dumps(msg))
    while True:
        raw = await _ws_recv(reader)
        obj = json.loads(raw)
        if obj.get("id") == msg_id:
            if "error" in obj:
                logger.debug("[Agent-TARS] CDP %s error: %s", method, obj["error"])
            return obj.get("result", {})


async def _cdp_screenshot_async(cdp_url: str, output_path: Path) -> bool:
    """Connect to a CDP endpoint, take a screenshot, write PNG to output_path."""
    parsed = urlparse(cdp_url)
    is_wss = cdp_url.startswith(("wss://", "ws://"))

    if not is_wss:
        # Local Chrome HTTP endpoint: resolve page WS URL via /json
        try:
            with urllib.request.urlopen(cdp_url.rstrip("/") + "/json", timeout=5) as resp:
                targets = json.loads(resp.read())
            pages = [t for t in targets if t.get("type") == "page"]
            if not pages:
                return False
            cdp_url = pages[0]["webSocketDebuggerUrl"]
            parsed = urlparse(cdp_url)
        except Exception:
            return False

    host = parsed.hostname or ""
    port = parsed.port or (443 if cdp_url.startswith("wss://") else 80)
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

    ssl_ctx: ssl.SSLContext | None = None
    if cdp_url.startswith("wss://"):
        ssl_ctx = ssl.create_default_context()

    try:
        reader, writer = await asyncio.open_connection(host, port, ssl=ssl_ctx)
    except Exception:
        return False

    try:
        if not await _ws_handshake(reader, writer, f"{host}:{port}", path):
            return False

        msg_id = 1
        session_id: str | None = None

        if not is_wss or "/devtools/page/" not in cdp_url:
            # Browser-level endpoint: need to attach to a page target
            targets_result = await _cdp_call(reader, writer, msg_id, "Target.getTargets", {})
            msg_id += 1
            target_infos = targets_result.get("targetInfos", [])
            pages = [t for t in target_infos if t.get("type") == "page"]
            if not pages:
                return False
            target_id = pages[0]["targetId"]
            attach_result = await _cdp_call(
                reader, writer, msg_id, "Target.attachToTarget",
                {"targetId": target_id, "flatten": True},
            )
            msg_id += 1
            session_id = attach_result.get("sessionId")
            if not session_id:
                return False

        ss_result = await _cdp_call(
            reader, writer, msg_id, "Page.captureScreenshot",
            {"format": "png", "quality": 80},
            session_id=session_id,
        )
        data = ss_result.get("data")
        if not data:
            return False

        output_path.write_bytes(base64.b64decode(data))
        return True
    except Exception:
        return False
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


def _take_iteration_screenshot(iteration: int, cdp_url: str, trajectory_dir: Path) -> None:
    """Take a CDP screenshot after an iteration completes. Runs in a background thread."""
    output_path = trajectory_dir / f"screenshot-cdp-{iteration}.png"
    if output_path.exists():
        return
    try:
        ok = asyncio.run(
            asyncio.wait_for(_cdp_screenshot_async(cdp_url, output_path), timeout=_CDP_SCREENSHOT_TIMEOUT)
        )
        if ok:
            logger.info("[Agent-TARS] CDP screenshot saved: %s", output_path.name)
        else:
            logger.debug("[Agent-TARS] CDP screenshot failed for iteration %d", iteration)
    except Exception as exc:
        logger.debug("[Agent-TARS] CDP screenshot error iteration %d: %s", iteration, exc)


def _is_excluded_dir(path: Path) -> bool:
    return path.name == "trajectory"


def find_event_stream_file(task_folder: Path) -> Path | None:
    """Find the event-stream.jsonl file in Agent-TARS output directory."""
    # Session-level: task_folder/<session>/event-stream.jsonl (newest by mtime)
    session_files = sorted(
        (p for p in task_folder.glob("*/event-stream.jsonl") if not _is_excluded_dir(p.parent)),
        key=lambda p: p.stat().st_mtime,
    )
    if session_files:
        return session_files[-1]

    # Loop-level: task_folder/<session>/loop-<N>/event-stream.jsonl (highest loop number)
    loop_files = sorted(
        (
            p
            for p in task_folder.glob("*/loop-*/event-stream.jsonl")
            if not _is_excluded_dir(p.parent.parent)
        ),
        key=lambda p: _loop_dir_sort_key(p.parent),
    )
    if loop_files:
        return loop_files[-1]

    return None


def parse_event_stream(file_path: Path) -> list[dict[str, Any]]:
    """Parse event-stream.jsonl file."""
    events = load_json_records(file_path)
    return [event for event in events if isinstance(event, dict)]


def calculate_metrics_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate metrics from event stream."""
    metrics = {"ttft_ms": 0, "end_to_end_ms": 0, "steps": 0}

    first_user_ts = next(
        (e.get("timestamp") for e in events if e.get("type") == "user_message"),
        None,
    )
    if not first_user_ts:
        return metrics

    assistant_msgs = [e for e in events if e.get("type") == "assistant_message"]
    if not assistant_msgs:
        return metrics

    first_ts = assistant_msgs[0].get("timestamp")
    last_ts = assistant_msgs[-1].get("timestamp")

    if first_ts:
        metrics["ttft_ms"] = first_ts - first_user_ts
    if last_ts:
        metrics["end_to_end_ms"] = last_ts - first_user_ts
    metrics["steps"] = len(assistant_msgs)

    return metrics


def extract_actions_from_events(events: list[dict[str, Any]]) -> list[str]:
    """Extract action history from events."""
    actions: list[str] = []
    for event in events:
        if event.get("type") != "assistant_message":
            continue

        tool_calls = event.get("toolCalls", [])
        for tool_call in tool_calls:
            func = tool_call.get("function", {})
            tool_name = func.get("name", "")

            if not (tool_name.startswith("browser_") or tool_name == "web_search"):
                continue

            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {}

            if tool_name == "browser_navigate":
                action = f"Navigate to {args.get('url', '')}"
            elif tool_name == "browser_click":
                action = f"Click element {args.get('index', args.get('selector', ''))}"
            elif tool_name == "browser_form_input_fill":
                action = f"Type into field: {args.get('value', '')[:50]}"
            elif tool_name == "web_search":
                action = f"Search: {args.get('query', '')}"
            else:
                action = tool_name

            actions.append(action)

    return actions


# Rough chars-per-token heuristic used when the LLM provider did not return
# explicit usage data in streaming chunks. Average English tokens are ~4 chars;
# for mixed CJK content this is slightly pessimistic, but the estimate is
# consistent and good enough for a leaderboard's magnitude comparison.
_CHARS_PER_TOKEN = 4.0


def _loop_sort_key(path: Path) -> int:
    try:
        return int(path.name.split("-", 1)[1])
    except (ValueError, IndexError):
        return 10**9


def _collect_llm_log_files(task_folder: Path, filename: str) -> list[Path]:
    """Find ``<task>/**/loop-*/<filename>`` in loop order, across known layouts.

    Agent-TARS has used three on-disk layouts over time:
    - ``trajectory/loop-*/`` (older)
    - ``api_logs/loop-*/`` (recent — we explicitly rename the session dir)
    - ``<random-session-id>/loop-*/`` (oldest — session dir not renamed)

    Rather than hard-coding every layout, we walk one level down from the
    task root and accept any subdirectory that has ``loop-N`` children.
    """
    if not task_folder.is_dir():
        return []

    roots: list[Path] = []
    # Pinned layouts first, so their loops come in a stable order.
    for name in ("trajectory", "api_logs"):
        candidate = task_folder / name
        if candidate.exists() and candidate.is_dir():
            roots.append(candidate)

    # Then any other first-level dir that looks like a session folder holding
    # loop-* entries. This catches the pre-rename "<sessionId>/" layout without
    # needing to guess its exact name.
    known = {"trajectory", "api_logs", "images"}
    for child in sorted(task_folder.iterdir()):
        if not child.is_dir() or child.name in known or child.name.startswith("."):
            continue
        try:
            has_loop = any(
                d.is_dir() and d.name.startswith("loop-")
                for d in child.iterdir()
            )
        except OSError as exc:
            logger.debug("Failed to scan %s for loop dirs: %s", child, exc)
            continue
        if has_loop:
            roots.append(child)

    seen: set[Path] = set()
    results: list[Path] = []
    for root in roots:
        try:
            loop_dirs = sorted(
                (d for d in root.iterdir() if d.is_dir() and d.name.startswith("loop-")),
                key=_loop_sort_key,
            )
        except OSError as exc:
            logger.debug("Failed to list loop dirs under %s: %s", root, exc)
            continue
        for loop_dir in loop_dirs:
            fp = loop_dir / filename
            if fp.exists() and fp not in seen:
                seen.add(fp)
                results.append(fp)
    return results


def find_trajectory_llm_responses(task_folder: Path) -> list[Path]:
    """Find all llm-response.jsonl files across trajectory/ and api_logs/."""
    return _collect_llm_log_files(task_folder, "llm-response.jsonl")


def extract_usage_from_llm_response(file_path: Path) -> dict[str, Any] | None:
    """Extract usage information from llm-response.jsonl.

    Streaming providers may emit the final token counts either on the very last
    chunk (common for OpenAI with ``stream_options.include_usage=true``) or on
    an intermediate ``message_delta`` event (Anthropic native). We take the
    *last* chunk that carries non-empty usage so both paths work.
    """
    last_usage = None
    try:
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                usage = obj.get("usage")
                if usage:
                    last_usage = usage
    except OSError as exc:
        logger.debug("Failed to read %s: %s", file_path, exc)
        return None

    return last_usage


def _text_length_from_request_messages(messages: Any) -> int:
    """Sum approximate input character count for a chat-completion request.

    ``messages`` is a list of ``{role, content}`` entries where ``content`` can
    be either a plain string or an OpenAI/Anthropic content-parts array. We
    only count text parts (tool args, system/user/assistant/tool text); image
    parts are ignored because their token cost depends on the model and we
    can't estimate it from raw bytes.
    """
    if not isinstance(messages, list):
        return 0
    total = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    total += len(text)
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    total += len(args)
    return total


def _text_length_from_response_stream(file_path: Path) -> int:
    """Sum completion character count across streaming chunks.

    Covers two payload shapes observed in Agent-TARS logs:
    - OpenAI-style chat.completion.chunk with ``choices[*].delta.content`` and
      ``delta.tool_calls[*].function.arguments``.
    - Whole-message payloads with ``choices[*].message.content`` / ``tool_calls``.
    """
    total = 0
    try:
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not isinstance(choices, list):
                    continue
                for ch in choices:
                    if not isinstance(ch, dict):
                        continue
                    for field in ("delta", "message"):
                        body = ch.get(field) or {}
                        if not isinstance(body, dict):
                            continue
                        content = body.get("content")
                        if isinstance(content, str):
                            total += len(content)
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict):
                                    text = part.get("text")
                                    if isinstance(text, str):
                                        total += len(text)
                        tool_calls = body.get("tool_calls") or []
                        if isinstance(tool_calls, list):
                            for tc in tool_calls:
                                if not isinstance(tc, dict):
                                    continue
                                fn = tc.get("function") or {}
                                args = fn.get("arguments")
                                if isinstance(args, str):
                                    total += len(args)
    except OSError as exc:
        logger.debug("Failed to read %s: %s", file_path, exc)
    return total


def _estimate_loop_tokens(
    response_path: Path,
) -> tuple[int, int] | None:
    """Estimate (prompt_tokens, completion_tokens) for a single loop.

    Returns ``None`` if no text was recovered (so the caller can skip the
    loop entirely rather than recording a zero-token entry).
    """
    request_path = response_path.with_name("llm-request.jsonl")
    prompt_chars = 0
    if request_path.exists():
        for rec in load_json_records(request_path):
            if not isinstance(rec, dict):
                continue
            # Agent-TARS wraps the raw HTTP request under rec["request"]; fall
            # back to the top level for other layouts.
            req = rec.get("request") if isinstance(rec.get("request"), dict) else rec
            prompt_chars += _text_length_from_request_messages(req.get("messages"))
    completion_chars = _text_length_from_response_stream(response_path)

    if prompt_chars == 0 and completion_chars == 0:
        return None

    prompt_tokens = int(prompt_chars / _CHARS_PER_TOKEN + 0.5) if prompt_chars else 0
    completion_tokens = int(completion_chars / _CHARS_PER_TOKEN + 0.5) if completion_chars else 0
    return prompt_tokens, completion_tokens


def extract_usage_summary(task_folder: Path) -> dict[str, Any]:
    """Aggregate usage across all LLM calls.

    Primary source is the explicit ``usage`` field in each loop's
    ``llm-response.jsonl``. When that's absent — typical for LiteLLM proxies
    that convert Anthropic streaming into OpenAI-style chunks without
    ``stream_options.include_usage=true`` — we fall back to a character-based
    estimate over the raw request/response text so that the token / cost
    columns are still populated (marked with ``token_estimation`` so consumers
    know it's approximate).
    """
    response_files = find_trajectory_llm_responses(task_folder)
    if not response_files:
        return {}

    total_prompt = 0
    total_completion = 0
    total_cached = 0
    entry_count = 0
    estimated_entry_count = 0

    for fp in response_files:
        usage = extract_usage_from_llm_response(fp)
        loop_prompt = 0
        loop_completion = 0
        loop_cached = 0
        counted = False

        if usage:
            loop_prompt = safe_int(usage.get("prompt_tokens", 0))
            loop_completion = safe_int(usage.get("completion_tokens", 0))
            prompt_details = usage.get("prompt_tokens_details")
            if isinstance(prompt_details, dict):
                loop_cached = safe_int(prompt_details.get("cached_tokens", 0))

            if loop_prompt == 0 and loop_completion == 0:
                total_tokens = safe_int(usage.get("total_tokens", 0))
                if total_tokens > 0:
                    loop_prompt = total_tokens
            counted = loop_prompt > 0 or loop_completion > 0

        if not counted:
            estimate = _estimate_loop_tokens(fp)
            if estimate is None:
                continue
            loop_prompt, loop_completion = estimate
            estimated_entry_count += 1

        total_prompt += loop_prompt
        total_completion += loop_completion
        total_cached += loop_cached
        entry_count += 1

    if entry_count == 0:
        return {}

    summary: dict[str, Any] = {
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_prompt_cached_tokens": total_cached,
        "total_tokens": total_prompt + total_completion,
        "entry_count": entry_count,
    }
    # Only tag the summary if at least one loop needed estimation; keep it out
    # of the payload when the provider actually returned usage, so downstream
    # consumers know the difference.
    if estimated_entry_count:
        summary["token_estimation"] = "char_heuristic"
        summary["estimated_entry_count"] = estimated_entry_count
    return summary


def _extract_screenshot_payload(event: dict[str, Any]) -> str | None:
    screenshot_data: str | None = None
    if event.get("type") == "environment_input":
        metadata = event.get("metadata")
        if isinstance(metadata, dict) and metadata.get("type") == "screenshot":
            screenshot_data = event.get("data")
        if not screenshot_data and "content" in event:
            for content_item in event.get("content", []):
                if not isinstance(content_item, dict):
                    continue
                screenshot_data = extract_base64_from_content_item(content_item)
                if screenshot_data:
                    break
    if not screenshot_data:
        screenshot_data = find_key_recursive(event, "currentScreenshot")
    return strip_base64_prefix(screenshot_data)


def _extract_environment_screenshot_payload(
    event: dict[str, Any],
    require_metadata: bool,
) -> str | None:
    if event.get("type") != "environment_input":
        return None

    metadata = event.get("metadata")
    if require_metadata and (not isinstance(metadata, dict) or metadata.get("type") != "screenshot"):
        return None

    if isinstance(metadata, dict) and metadata.get("type") == "screenshot":
        screenshot_data = event.get("data")
        if isinstance(screenshot_data, str):
            return strip_base64_prefix(screenshot_data)

    content = event.get("content", [])
    if isinstance(content, list):
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            screenshot_data = extract_base64_from_content_item(content_item)
            if screenshot_data:
                return screenshot_data
    return None


def _hash_base64_payload(payload: str) -> str:
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _loop_dir_sort_key(path: Path) -> int:
    try:
        return int(path.name.split("-", 1)[1])
    except (ValueError, IndexError):
        return 0


def _loop_label(path: Path) -> str:
    try:
        return str(int(path.name.split("-", 1)[1]))
    except (ValueError, IndexError):
        return path.name


def extract_screenshots_from_snapshot(snapshot_dir: Path, output_dir: Path) -> list[str]:
    """Extract screenshots from a snapshot directory (event-stream.jsonl)."""
    saved_screenshots: list[str] = []
    seen_hashes: set[str] = set()

    if not snapshot_dir.exists():
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    def save_screenshot(payload: str | None, file_name: str) -> None:
        if not payload:
            return
        payload_hash = _hash_base64_payload(payload)
        if payload_hash in seen_hashes:
            return
        if decode_base64_to_file(payload, output_dir / file_name):
            saved_screenshots.append(file_name)
            seen_hashes.add(payload_hash)

    root_event_stream = snapshot_dir / "event-stream.jsonl"
    if root_event_stream.exists():
        events = parse_event_stream(root_event_stream)
        screenshot_events = [
            e
            for e in events
            if isinstance(e, dict) and e.get("type") == "environment_input" and "content" in e
        ]

        for idx, event in enumerate(screenshot_events, 1):
            screenshot_data = _extract_environment_screenshot_payload(
                event,
                require_metadata=False,
            )
            file_name = f"screenshot-root-{idx}.png"
            save_screenshot(screenshot_data, file_name)

    loop_dirs = sorted(snapshot_dir.glob("loop-*"), key=_loop_dir_sort_key)

    for loop_dir in loop_dirs:
        event_stream_file = loop_dir / "event-stream.jsonl"
        if not event_stream_file.exists():
            continue

        events = parse_event_stream(event_stream_file)
        env_input_count = sum(
            1 for e in events if isinstance(e, dict) and e.get("type") == "environment_input"
        )

        for i, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            screenshot_data = _extract_environment_screenshot_payload(
                event,
                require_metadata=True,
            )
            if not screenshot_data:
                continue

            loop_label = _loop_label(loop_dir)
            if i > 0 and env_input_count > 1:
                file_name = f"screenshot-{loop_label}-{i}.png"
            else:
                file_name = f"screenshot-{loop_label}.png"

            save_screenshot(screenshot_data, file_name)

    if not saved_screenshots:
        logger.info(
            "No environment_input screenshots found in %s; falling back to currentScreenshot",
            snapshot_dir,
        )
        if root_event_stream.exists():
            events = parse_event_stream(root_event_stream)
            for idx, event in enumerate(events, 1):
                screenshot_data = _extract_screenshot_payload(event)
                file_name = f"screenshot-root-{idx}.png"
                save_screenshot(screenshot_data, file_name)

        for loop_dir in loop_dirs:
            event_stream_file = loop_dir / "event-stream.jsonl"
            if not event_stream_file.exists():
                continue
            events = parse_event_stream(event_stream_file)
            for i, event in enumerate(events, 1):
                if not isinstance(event, dict):
                    continue
                screenshot_data = _extract_screenshot_payload(event)
                if not screenshot_data:
                    continue
                loop_label = _loop_label(loop_dir)
                file_name = f"screenshot-{loop_label}-{i}.png"
                save_screenshot(screenshot_data, file_name)

    return saved_screenshots


def extract_task_screenshots(task_workspace: Path) -> list[str]:
    """Orchestrate extraction of screenshots from task workspace."""
    trajectory_dir = task_workspace / "trajectory"
    all_saved_screenshots: list[str] = []

    session_dirs: list[Path] = []
    if trajectory_dir.exists():
        session_dirs.extend(
            [
                d
                for d in trajectory_dir.iterdir()
                if d.is_dir() and not d.name.startswith(("loop-", "screenshot-"))
            ]
        )

    root_session_dirs = [
        d
        for d in task_workspace.iterdir()
        if d.is_dir()
        and (
            d.name == "api_logs"  # normalized name after rename
            or (d.name not in ["trajectory", "images"] and len(d.name) > 15)  # raw session ID
        )
    ]

    if root_session_dirs:
        session_dirs.extend(root_session_dirs)
        trajectory_dir.mkdir(parents=True, exist_ok=True)

    output_dir = trajectory_dir

    if not session_dirs:
        if (trajectory_dir / "event-stream.jsonl").exists():
            all_saved_screenshots.extend(
                extract_screenshots_from_snapshot(trajectory_dir, output_dir)
            )
    else:
        for session_dir in session_dirs:
            all_saved_screenshots.extend(extract_screenshots_from_snapshot(session_dir, output_dir))

    return all_saved_screenshots


def enrich_result_json(
    task_id: str,
    task_workspace: Path,
    *,
    model_id: str = "",
    browser_id: str = "",
    config: dict[str, Any] | None = None,
) -> AgentResult | None:
    """Enrich result.json with action history and metrics from Agent-TARS output.

    ``model_id`` / ``browser_id`` / ``config`` are passed through from the caller
    so that the written ``result.json`` carries the same identity/config fields
    that other agents (browser-use, skyvern) record. Without this, downstream
    tooling (leaderboard, evaluators) can't tell which model or browser this run
    used.
    """
    event_stream_path = find_event_stream_file(task_workspace)
    if not event_stream_path:
        logger.debug("No event stream found for task %s", task_id)
        return None

    events = parse_event_stream(event_stream_path)
    if not events:
        logger.debug("Empty or invalid event stream for task %s", task_id)
        return None

    actions = extract_actions_from_events(events)
    raw_metrics = calculate_metrics_from_events(events)
    usage_data = extract_usage_summary(task_workspace)

    screenshot_files = extract_task_screenshots(task_workspace)

    final_response = next(
        (e.get("content", "") for e in reversed(events) if e.get("type") == "assistant_message"),
        "[No final response]",
    )

    has_activity = bool(actions) or raw_metrics["steps"] > 0
    env_status = "success" if has_activity else "failed"
    agent_done = "done" if has_activity else "error"

    return AgentResult(
        task_id=task_id,
        timestamp=datetime.now(UTC),
        env_status=env_status,  # type: ignore[arg-type]
        agent_done=agent_done,  # type: ignore[arg-type]
        error=None if has_activity else "No actions or steps detected",
        answer=final_response,
        model_id=model_id or "",
        browser_id=browser_id or "",
        action_history=actions,
        screenshots=screenshot_files,
        metrics=AgentMetrics(
            ttft_ms=raw_metrics.get("ttft_ms") if raw_metrics.get("ttft_ms") else None,
            end_to_end_ms=raw_metrics.get("end_to_end_ms", 0),
            steps=raw_metrics.get("steps", 0),
            usage=AgentUsage(**usage_data) if usage_data else None,
        ),
        config=config or {},
    )


def _start_cdp_proxy_server(wss_url: str) -> tuple[http.server.HTTPServer, int]:
    """Start a local HTTP server that emulates Chrome's /json/version endpoint.

    Agent-TARS calls ``fetch(cdpEndpoint)`` and reads ``webSocketDebuggerUrl``
    from the JSON response.  Cloud browsers (e.g. Lexmount) only expose a
    WebSocket URL (wss://), so we bridge the gap with a minimal local proxy.
    """

    class _CDPVersionHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in ("/json/version", "/json"):
                self.send_response(404)
                self.end_headers()
                return
            payload = json.dumps({"webSocketDebuggerUrl": wss_url}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass  # suppress request logging

    server = http.server.HTTPServer(("127.0.0.1", 0), _CDPVersionHandler)
    port: int = server.server_address[1]
    ready = threading.Event()

    def _serve() -> None:
        ready.set()
        server.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    ready.wait(timeout=2.0)
    logger.debug("CDP proxy server started on http://127.0.0.1:%d/json/version", port)
    return server, port


@register_agent
class AgentTARSAgent(CLIAgent):
    """
    Browser automation agent using the Agent-TARS CLI.

    Agent-TARS is executed as an external process via subprocess.
    """

    name = "Agent-TARS"

    def run_task(
        self,
        task_info: dict[str, Any],
        agent_config: dict[str, Any],
        task_workspace: Path,
    ) -> AgentResult | dict[str, Any]:
        """Execute a browser automation task using Agent-TARS CLI."""

        task_id = task_info["task_id"]
        query = task_info.get("prompt") or task_info.get("task_text", "")
        # Build command
        cmd = ["agent-tars.cmd" if IS_WINDOWS else "agent-tars", "run"]

        # Resolve config params (with env fallback for secrets)
        model_provider = agent_config.get("model_provider")
        model_id = self.get_model_id(agent_config)
        # get_api_key reads "api_key" from config + AGENT_TARS_API_KEY env fallback.
        # "model_apikey" is a legacy Agent-TARS-specific alias kept for backwards compat.
        model_apikey = self.get_api_key(agent_config, "AGENT_TARS_API_KEY") or agent_config.get("model_apikey")
        model_baseurl = self.get_base_url(agent_config, "AGENT_TARS_BASE_URL") or agent_config.get("model_baseurl")
        browser_control = agent_config.get("browser_control", "dom")
        timeout = self.get_timeout(agent_config, 300)
        browser_id = agent_config.get("browser_id", "local")

        temperature = agent_config.get("temperature")
        max_tokens = agent_config.get("max_tokens")
        max_turns = agent_config.get("max_turns")

        # Identity + config snapshot written into result.json so that downstream
        # tooling (leaderboard, evaluators) can tell which model / browser this
        # run used. Mirrors what skyvern / browser-use already do.
        resolved_model_id: str = str(model_id or "")
        resolved_browser_id: str = str(browser_id or "")
        config_info: dict[str, Any] = {
            "timeout_seconds": timeout,
            "model_provider": model_provider,
            "model_id": resolved_model_id,
            "browser_id": resolved_browser_id,
            "browser_control": browser_control,
        }
        if temperature is not None:
            config_info["temperature"] = float(temperature)
        if max_tokens is not None:
            config_info["max_completion_tokens"] = int(max_tokens)
        if max_turns is not None:
            config_info["max_iterations"] = int(max_turns)

        def _new_result(
            *,
            env_status: str,
            agent_done: str,
            error: str | None = None,
            answer: str = "",
            action_history: list[str] | None = None,
            screenshots: list[str] | None = None,
            metrics: AgentMetrics | None = None,
        ) -> AgentResult:
            return AgentResult(
                task_id=task_id,
                timestamp=datetime.now(UTC),
                env_status=env_status,  # type: ignore[arg-type]
                agent_done=agent_done,  # type: ignore[arg-type]
                error=error,
                answer=answer,
                model_id=resolved_model_id,
                browser_id=resolved_browser_id,
                action_history=action_history or [],
                screenshots=screenshots or [],
                metrics=metrics or AgentMetrics(end_to_end_ms=0, steps=0),
                config=config_info,
            )

        warn_if_local_proxy_unsupported(agent_config, self.name)
        with open_browser_session(
            browser_id=browser_id,
            agent_name=self.name,
            agent_config=agent_config,
        ) as session_context:
            # Prefer the backend-resolved id (e.g. the actual cloud backend
            # that got picked) over the raw config value.
            backend_id = getattr(session_context, "backend_id", None)
            if isinstance(backend_id, str) and backend_id.strip():
                resolved_browser_id = backend_id.strip()
                config_info["browser_id"] = resolved_browser_id
            # Build CLI args
            cmd_args = []
            if model_provider:
                cmd_args.extend(["--model.provider", model_provider])
            if model_id:
                cmd_args.extend(["--model.id", model_id])
            if model_apikey:
                cmd_args.extend(["--model.apiKey", model_apikey])
            if model_baseurl:
                cmd_args.extend(["--model.baseURL", model_baseurl])

            # temperature, max_tokens, max_turns are not CLI flags — pass via --config file
            tmp_cfg_path: str | None = None
            extra_cfg: dict[str, Any] = {}
            if temperature is not None:
                extra_cfg["temperature"] = float(temperature)
            if max_tokens is not None:
                extra_cfg["maxCompletionTokens"] = int(max_tokens)
            if max_turns is not None:
                extra_cfg["maxIterations"] = int(max_turns)
            if extra_cfg:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, encoding="utf-8"
                ) as tmp_cfg:
                    json.dump(extra_cfg, tmp_cfg)
                    tmp_cfg_path = tmp_cfg.name
                cmd_args.extend(["--config", tmp_cfg_path])

            clean_query = " ".join(line.strip() for line in query.splitlines() if line.strip())
            cmd_args.extend(["--input", clean_query])
            tool_call_engine = agent_config.get("tool_call_engine")
            if not tool_call_engine:
                tool_call_engine = (
                    "native"
                    if model_provider in ("openai", "anthropic", "azure")
                    else "prompt_engineering"
                )
            config_info["tool_call_engine"] = tool_call_engine

            # Tool filtering: by default only expose browser_* tools to the LLM.
            # Non-browser tools (filesystem, shell, web_search) are irrelevant for
            # web benchmarks and inflate the tool list, which can cause proxy issues.
            tool_include = agent_config.get("tool_include", "browser_")
            tool_exclude = agent_config.get("tool_exclude")
            if tool_include:
                cmd_args.extend(["--tool.include", str(tool_include)])
            if tool_exclude:
                cmd_args.extend(["--tool.exclude", str(tool_exclude)])

            cmd_args.extend(
                [
                    "--format",
                    "json",
                    "--browser.control",
                    browser_control,
                    "--debug",
                    "--toolCallEngine",
                    tool_call_engine,
                ]
            )
            cmd_args.extend(["--workspace", str(task_workspace.absolute())])

            snapshot_path = task_workspace / "trajectory"
            snapshot_path.mkdir(parents=True, exist_ok=True)
            cmd_args.extend(
                ["--snapshot.enable", "--snapshot.snapshotPath", str(snapshot_path.absolute())]
            )
            # --headless is the Agent-TARS CLI flag for non-interactive (headless UI)
            # execution — it must always be present so the CLI runs the task and
            # exits instead of starting a persistent web server on port 8888.
            cmd_args.append("--headless")
            cdp_proxy_server: http.server.HTTPServer | None = None
            if session_context.transport == "cdp" and session_context.cdp_url:
                cdp_url = session_context.cdp_url
                if cdp_url.startswith(("ws://", "wss://")):
                    # Cloud browser (e.g. Lexmount): only a WebSocket URL is available.
                    # Agent-TARS fetches cdpEndpoint as HTTP /json/version, so we spin up
                    # a local proxy that serves {"webSocketDebuggerUrl": "<wss_url>"}.
                    try:
                        cdp_proxy_server, proxy_port = _start_cdp_proxy_server(cdp_url)
                        cmd_args.extend(
                            ["--browser.cdpEndpoint", f"http://127.0.0.1:{proxy_port}/json/version"]
                        )
                    except OSError as exc:
                        return _new_result(
                            env_status="failed",
                            agent_done="error",
                            error=f"Failed to start CDP proxy server: {exc}",
                        )
                else:
                    # Native CDP backend (e.g. http://localhost:9222): Chrome DevTools
                    # Protocol already exposes /json/version at that base URL, so pass
                    # it directly without a local proxy.
                    cmd_args.extend(["--browser.cdpEndpoint", cdp_url])

            full_cmd = cmd + cmd_args
            logger.info(f"Executing Agent-TARS for task {task_id}")

            # CDP URL for per-iteration screenshots (wss:// for cloud, http:// for local).
            _screenshot_cdp_url: str | None = (
                session_context.cdp_url
                if session_context.transport == "cdp" and session_context.cdp_url
                else None
            )
            _screenshot_threads: list[threading.Thread] = []
            _screenshot_claimed: set[int] = set()
            _screenshot_lock = threading.Lock()

            # Execute
            _TARS_LOG_KEYS = (
                "LoopExecutor [Iteration]",
                "ToolProcessor",
                "LLMProcessor [Agent]",
                "AgentRunner [Session]",
                "Enriched result.json",
            )

            def _line_hook(line: str) -> None:
                clean = line.strip()
                if not clean:
                    return
                if any(k in clean for k in _TARS_LOG_KEYS):
                    logger.info("[Agent-TARS] %s", clean)
                elif "error" in clean.lower() and "debug" not in clean.lower():
                    logger.warning("[Agent-TARS] %s", clean)
                # Trigger a CDP screenshot after each iteration completes.
                if _screenshot_cdp_url:
                    m = _ITER_COMPLETE_RE.search(clean)
                    if m:
                        iteration_num = int(m.group(1))
                        with _screenshot_lock:
                            if iteration_num in _screenshot_claimed:
                                return
                            _screenshot_claimed.add(iteration_num)
                        t = threading.Thread(
                            target=_take_iteration_screenshot,
                            args=(iteration_num, _screenshot_cdp_url, snapshot_path),
                            daemon=True,
                        )
                        t.start()
                        _screenshot_threads.append(t)

            execution_error: str | None = None
            returncode = -1
            try:
                try:
                    returncode, _, execution_error = self._run_subprocess(
                        full_cmd,
                        timeout=timeout,
                        task_workspace=task_workspace,
                        collect_stdout=False,
                        stdout_line_hook=_line_hook,
                        stderr_line_hook=_line_hook,
                    )
                except FileNotFoundError:
                    return _new_result(
                        env_status="failed",
                        agent_done="error",
                        error=f"Executable '{cmd[0]}' not found. Please install Agent-TARS.",
                    )
                if execution_error and "Timeout" in execution_error:
                    logger.error("Agent-TARS task %s timed out after %d seconds", task_id, timeout)
            finally:
                if cdp_proxy_server:
                    cdp_proxy_server.shutdown()
                if tmp_cfg_path:
                    try:
                        os.unlink(tmp_cfg_path)
                    except OSError:
                        pass

            # Wait for in-flight CDP screenshot threads before processing results.
            for t in _screenshot_threads:
                t.join(timeout=_CDP_SCREENSHOT_TIMEOUT + 2)

            # Normalize Agent-TARS session folder → api_logs for consistent naming.
            # Agent-TARS creates a random session-ID dir (e.g. "VbM5_xxx") directly
            # inside task_workspace; rename it to "api_logs" so the path is stable.
            _api_logs = task_workspace / "api_logs"
            if not _api_logs.exists():
                _excluded = {"trajectory", "images", "api_logs"}
                for _d in sorted(task_workspace.iterdir()):
                    if _d.is_dir() and _d.name not in _excluded:
                        try:
                            _d.rename(_api_logs)
                            logger.debug("Renamed session dir %s → api_logs", _d.name)
                        except OSError as _e:
                            logger.warning("Could not rename session dir %s: %s", _d.name, _e)
                        break

            # Try to enrich result from Agent-TARS output (event-stream, trajectory)
            enriched_result = None
            try:
                enriched_result = enrich_result_json(
                    task_id,
                    task_workspace,
                    model_id=resolved_model_id,
                    browser_id=resolved_browser_id,
                    config=config_info,
                )
                if enriched_result:
                    # Write enriched result to result.json
                    result_json_path = task_workspace / "result.json"
                    with open(result_json_path, "w", encoding="utf-8") as f:
                        json.dump(
                            enriched_result.model_dump(mode="json"), f, indent=2, ensure_ascii=False
                        )
                    logger.info(
                        f"Enriched result.json with {enriched_result.metrics.steps} steps, "
                        f"{len(enriched_result.action_history)} actions"
                    )
                    return enriched_result
            except (OSError, ValueError, TypeError, KeyError) as e:
                logger.warning(f"Failed to enrich result for task {task_id}: {e}")

            # Fallback: Read existing result.json if generated
            result_json_path = task_workspace / "result.json"
            if result_json_path.exists():
                try:
                    with open(result_json_path, encoding="utf-8") as f:
                        result_data = json.load(f)

                        # Check if result is already an AgentResult (has schema_version)
                        if "schema_version" in result_data:
                            return AgentResult.model_validate(result_data)

                        # Legacy dict: check if the result indicates failure
                        data_status = result_data.get("status", "success")

                        # Check if there were actual steps taken
                        steps = result_data.get("metrics", {}).get("steps", 0)
                        if steps == 0 and returncode == 0:
                            stdout_file = task_workspace / "stdout.txt"
                            error_msg = None
                            if stdout_file.exists():
                                try:
                                    with open(stdout_file, encoding="utf-8") as sf:
                                        stdout_content = sf.read()
                                        if 'finishReason": "error"' in stdout_content:
                                            match = re.search(
                                                r'"content":\s*"([^"]*error[^"]*)"',
                                                stdout_content,
                                                re.IGNORECASE,
                                            )
                                            if match:
                                                error_msg = match.group(1)
                                                error_msg = error_msg.replace("\\n", " ").strip()
                                except (OSError, UnicodeDecodeError) as exc:
                                    logger.warning(
                                        "Failed to inspect stdout for task %s: %s", task_id, exc
                                    )

                            if error_msg:
                                logger.error(f"Agent-TARS task {task_id} failed: {error_msg}")
                                data_status = "failed"
                                execution_error = error_msg

                        # Map legacy status → (env_status, agent_done)
                        if data_status in ("failed", "error"):
                            env_status = "failed"
                            agent_done = "error"
                        elif execution_error and "Timeout" in execution_error:
                            env_status = "success"
                            agent_done = "timeout"
                        else:
                            env_status = "success"
                            agent_done = "done"

                        raw_metrics = result_data.get("metrics", {})
                        usage_data = raw_metrics.get("usage", {})
                        return _new_result(
                            env_status=env_status,
                            agent_done=agent_done,
                            answer=result_data.get("final_response", result_data.get("answer", "")),
                            error=execution_error if env_status == "failed" else None,
                            action_history=result_data.get("action_history", []),
                            screenshots=result_data.get(
                                "all_screenshots", result_data.get("screenshots", [])
                            ),
                            metrics=AgentMetrics(
                                ttft_ms=raw_metrics.get("ttft_ms"),
                                end_to_end_ms=raw_metrics.get("end_to_end_ms", 0),
                                steps=raw_metrics.get("steps", 0),
                                usage=AgentUsage(**usage_data) if usage_data else None,
                            ),
                        )
                except (OSError, json.JSONDecodeError) as e:
                    logger.error(f"Failed to read result.json for task {task_id}: {e}")

            # Fallback return
            if returncode == 0 and not execution_error:
                env_status = "success"
                agent_done = "done"
            elif execution_error and "Timeout" in execution_error:
                env_status = "success"
                agent_done = "timeout"
            else:
                env_status = "failed"
                agent_done = "error"
            return _new_result(
                env_status=env_status,
                agent_done=agent_done,
                error=execution_error if env_status == "failed" else None,
            )
