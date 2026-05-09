"""
OpenAI CUA (Computer-Using Agent) — built-in ``computer`` tool integration.

Uses the OpenAI Responses API with the ``computer`` tool to drive a browser
via a screenshot → actions → screenshot loop.  Playwright executes the returned
UI actions (click, type, scroll, keypress, drag, etc.) inside a browser session
managed by ``open_browser_session``.

Prerequisites
=============
* ``openai`` (core dependency, already installed)
* ``playwright`` (``pip install playwright && playwright install chromium``)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from browseruse_bench.agents.base import BaseAgent
from browseruse_bench.agents.registry import register_agent
from browseruse_bench.browsers import BrowserSessionContext, open_browser_session
from browseruse_bench.browsers.providers.local import warn_if_local_proxy_unsupported
from browseruse_bench.schemas import AgentMetrics, AgentResult, AgentUsage

logger = logging.getLogger(__name__)

_KEY_MAP: dict[str, str] = {
    "ENTER": "Enter",
    "RETURN": "Enter",
    "TAB": "Tab",
    "SPACE": " ",
    "BACKSPACE": "Backspace",
    "DELETE": "Delete",
    "ESCAPE": "Escape",
    "ARROWUP": "ArrowUp",
    "ARROWDOWN": "ArrowDown",
    "ARROWLEFT": "ArrowLeft",
    "ARROWRIGHT": "ArrowRight",
    "CTRL": "Control",
    "META": "Meta",
    "ALT": "Alt",
    "SHIFT": "Shift",
    "HOME": "Home",
    "END": "End",
    "PAGEUP": "PageUp",
    "PAGEDOWN": "PageDown",
}


def _normalize_key(key: str) -> str:
    return _KEY_MAP.get(key.upper(), key)


@register_agent
class OpenAICUAAgent(BaseAgent):
    """Browser automation via OpenAI Responses API ``computer`` tool."""

    name = "openai-cua"

    def run_task(
        self,
        task_info: dict[str, Any],
        agent_config: dict[str, Any],
        task_workspace: Path,
    ) -> AgentResult:
        timeout = self.get_timeout(agent_config, 300)
        browser_id = agent_config.get("browser_id", "Chrome-Local")
        warn_if_local_proxy_unsupported(agent_config, self.name)

        with open_browser_session(
            browser_id=browser_id,
            agent_name=self.name,
            agent_config=agent_config,
        ) as session_context:
            return asyncio.run(
                self._run_with_timeout(
                    task_info, agent_config, task_workspace,
                    timeout, session_context,
                )
            )

    async def _run_with_timeout(
        self,
        task_info: dict[str, Any],
        agent_config: dict[str, Any],
        task_workspace: Path,
        timeout: int,
        session_context: BrowserSessionContext,
    ) -> AgentResult:
        try:
            return await asyncio.wait_for(
                self._run_task_async(
                    task_info, agent_config, task_workspace,
                    timeout, session_context,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            task_id = task_info.get("task_id", "unknown")
            task_prompt = self.build_task_prompt(task_info)
            model_id = self.get_model_id(agent_config) or "computer-use-preview"
            logger.error("Task %s timed out after %d seconds", task_id, timeout)
            error_msg = f"Timeout after {timeout} seconds"
            return AgentResult(
                task_id=task_id,
                task=task_prompt,
                timestamp=datetime.now(UTC),
                env_status="success",  # type: ignore[arg-type]
                agent_done="timeout",  # type: ignore[arg-type]
                agent_success=None,
                answer=f"[Task Failed: {error_msg}]",
                model_id=model_id,
                browser_id=session_context.backend_id,
                metrics=AgentMetrics(end_to_end_ms=timeout * 1000, steps=0),
                error=None,
            )

    async def _run_task_async(
        self,
        task_info: dict[str, Any],
        agent_config: dict[str, Any],
        task_workspace: Path,
        timeout: int,
        session_context: BrowserSessionContext,
    ) -> AgentResult:
        import openai as openai_mod
        from openai import AsyncOpenAI
        from playwright.async_api import async_playwright

        task_id = task_info["task_id"]
        task_prompt = self.build_task_prompt(task_info)
        url = task_info.get("url", "")
        model_id = self.get_model_id(agent_config) or "computer-use-preview"
        api_key = self.get_api_key(agent_config, "OPENAI_API_KEY")
        base_url = self.get_base_url(agent_config, "OPENAI_BASE_URL")
        max_steps = self.get_max_steps(agent_config, 30)
        display_w = int(agent_config.get("display_width", 1440))
        display_h = int(agent_config.get("display_height", 900))

        trajectory_dir = task_workspace / "trajectory"
        trajectory_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.monotonic()
        error_msg: str | None = None
        final_answer = ""
        action_history: list[str] = []
        steps = 0
        total_input_tokens = 0
        total_output_tokens = 0

        client_kwargs: dict[str, Any] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if base_url:
            client_kwargs["base_url"] = base_url
        client = AsyncOpenAI(**client_kwargs)

        pw = None
        browser = None
        page = None
        try:
            pw = await async_playwright().start()

            if session_context.transport == "cdp" and session_context.cdp_url:
                browser = await pw.chromium.connect_over_cdp(session_context.cdp_url)
                contexts = browser.contexts
                if contexts:
                    page = contexts[0].pages[0] if contexts[0].pages else await contexts[0].new_page()
                else:
                    ctx = await browser.new_context()
                    page = await ctx.new_page()
            else:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page()

            await page.set_viewport_size({"width": display_w, "height": display_h})
            if url:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            tools = [{
                "type": "computer_use_preview",
                "display_width": display_w,
                "display_height": display_h,
                "environment": "browser",
            }]

            screenshot_b64 = base64.b64encode(
                await page.screenshot(type="png")
            ).decode()
            self.save_screenshot(screenshot_b64, 1, trajectory_dir)

            # First request: user message with task text + initial screenshot as input_image.
            # computer_call_output is only valid as a reply to a model-issued computer_call.
            response = await client.responses.create(
                model=model_id,
                tools=tools,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": task_prompt},
                            {
                                "type": "input_image",
                                "image_url": f"data:image/png;base64,{screenshot_b64}",
                            },
                        ],
                    },
                ],
                truncation="auto",
            )

            previous_response_id = response.id
            if hasattr(response, "usage") and response.usage:
                total_input_tokens += getattr(response.usage, "input_tokens", 0)
                total_output_tokens += getattr(response.usage, "output_tokens", 0)

            for _ in range(max_steps):
                computer_call = None
                for item in response.output:
                    if getattr(item, "type", None) == "computer_call":
                        computer_call = item
                    elif getattr(item, "type", None) == "message":
                        for block in getattr(item, "content", []):
                            if getattr(block, "type", None) == "output_text":
                                final_answer = block.text

                if not computer_call:
                    break

                action = getattr(computer_call, "action", None)
                if action is not None:
                    desc = await self._execute_action(page, action)
                    action_history.append(desc)

                steps += 1
                await asyncio.sleep(0.5)

                screenshot_b64 = base64.b64encode(
                    await page.screenshot(type="png")
                ).decode()
                self.save_screenshot(screenshot_b64, steps + 1, trajectory_dir)

                response = await client.responses.create(
                    model=model_id,
                    tools=tools,
                    previous_response_id=previous_response_id,
                    input=[{
                        "type": "computer_call_output",
                        "call_id": computer_call.call_id,
                        "output": {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{screenshot_b64}",
                        },
                    }],
                    truncation="auto",
                )
                previous_response_id = response.id
                if hasattr(response, "usage") and response.usage:
                    total_input_tokens += getattr(response.usage, "input_tokens", 0)
                    total_output_tokens += getattr(response.usage, "output_tokens", 0)

        except openai_mod.APIError as exc:
            error_msg = f"OpenAI API error: {exc}"
            logger.error("Task %s OpenAI API error: %s", task_id, exc)
        except TimeoutError as exc:
            # Page-level / SDK-level timeouts that are not the outer deadline.
            error_msg = f"Inner timeout: {exc}"
            logger.error("Task %s inner timeout: %s", task_id, exc)
        except (RuntimeError, OSError, ValueError, TypeError, KeyError) as exc:
            error_msg = str(exc)
            logger.error("Task %s execution error: %s", task_id, exc)
        finally:
            if browser:
                try:
                    await browser.close()
                except (RuntimeError, OSError):
                    pass
            if pw:
                try:
                    await pw.stop()
                except (RuntimeError, OSError):
                    pass

        end_to_end_ms = int((time.monotonic() - t0) * 1000)

        if error_msg and "Timeout" in error_msg:
            env_status, agent_done = "success", "timeout"
        elif error_msg:
            env_status, agent_done = "failed", "error"
        elif steps >= max_steps:
            env_status, agent_done = "success", "max_steps"
        else:
            env_status, agent_done = "success", "done"

        agent_success: bool | None = None
        if agent_done == "done":
            agent_success = bool(final_answer)

        if not final_answer and error_msg:
            final_answer = f"[Task Failed: {error_msg}]"

        usage_obj = None
        if total_input_tokens + total_output_tokens > 0:
            usage_obj = AgentUsage(
                total_prompt_tokens=total_input_tokens,
                total_completion_tokens=total_output_tokens,
            )

        return AgentResult(
            task_id=task_id,
            task=task_prompt,
            timestamp=datetime.now(UTC),
            env_status=env_status,  # type: ignore[arg-type]
            agent_done=agent_done,  # type: ignore[arg-type]
            agent_success=agent_success,
            answer=final_answer,
            model_id=model_id,
            browser_id=session_context.backend_id,
            action_history=action_history,
            metrics=AgentMetrics(
                end_to_end_ms=end_to_end_ms,
                steps=steps,
                usage=usage_obj,
            ),
            config={
                "timeout_seconds": timeout,
                "model_id": model_id,
                "display_width": display_w,
                "display_height": display_h,
                "max_steps": max_steps,
                "browser_id": session_context.backend_id,
            },
            error=error_msg if env_status == "failed" else None,
        )

    @staticmethod
    async def _execute_action(page: Any, action: Any) -> str:
        action_type = getattr(action, "type", str(action))

        if action_type == "click":
            x, y = action.x, action.y
            button = getattr(action, "button", "left")
            keys = [_normalize_key(k) for k in (getattr(action, "keys", None) or [])]
            for k in keys:
                await page.keyboard.down(k)
            await page.mouse.click(x, y, button=button)
            for k in reversed(keys):
                await page.keyboard.up(k)
            return f"click({x},{y} button={button})"

        if action_type == "double_click":
            x, y = action.x, action.y
            await page.mouse.dblclick(x, y)
            return f"double_click({x},{y})"

        if action_type == "type":
            text = action.text
            await page.keyboard.type(text, delay=30)
            return f"type({text[:40]}{'...' if len(text) > 40 else ''})"

        if action_type == "keypress":
            raw_keys = action.keys if isinstance(action.keys, list) else [action.keys]
            normalized = [_normalize_key(k) for k in raw_keys]
            if not normalized:
                return "keypress(empty)"
            if len(normalized) > 1:
                combo = "+".join(normalized)
                await page.keyboard.press(combo)
            else:
                await page.keyboard.press(normalized[0])
            return f"keypress({'+'.join(normalized)})"

        if action_type == "scroll":
            x, y = action.x, action.y
            dx = getattr(action, "scroll_x", 0)
            dy = getattr(action, "scroll_y", 0)
            await page.mouse.move(x, y)
            await page.mouse.wheel(dx, dy)
            return f"scroll({x},{y} dx={dx} dy={dy})"

        if action_type == "drag":
            path = action.path
            if len(path) >= 2:
                start = path[0]
                await page.mouse.move(start["x"], start["y"])
                await page.mouse.down()
                for pt in path[1:]:
                    await page.mouse.move(pt["x"], pt["y"])
                await page.mouse.up()
            return f"drag(points={len(path)})"

        if action_type == "move":
            x, y = action.x, action.y
            await page.mouse.move(x, y)
            return f"move({x},{y})"

        if action_type == "wait":
            ms = getattr(action, "ms", 2000)
            await asyncio.sleep(ms / 1000)
            return f"wait({ms}ms)"

        if action_type == "screenshot":
            return "screenshot"

        return f"unknown({action_type})"
