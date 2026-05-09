"""
DeepBrowseAgent - Browser automation using the DeepBrowse SDK.

This agent runs DeepBrowse in-process via its Python SDK and uses the
browseruse-bench browser session manager for remote/local browser lifecycle.
"""

from __future__ import annotations

import asyncio
import importlib
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

DeepBrowseAgentSDK: type[Any] | None = None
BrowserProfileSDK: type[Any] | None = None
BrowserSessionSDK: type[Any] | None = None
_create_llm: Any | None = None
_DEEPBROWSE_IMPORT_ERROR: str | None = None


def _load_deepbrowse_dependencies() -> None:
    global DeepBrowseAgentSDK, BrowserProfileSDK, BrowserSessionSDK, _create_llm, _DEEPBROWSE_IMPORT_ERROR

    if (
        DeepBrowseAgentSDK is not None
        and BrowserProfileSDK is not None
        and BrowserSessionSDK is not None
        and _create_llm is not None
    ):
        return
    if _DEEPBROWSE_IMPORT_ERROR:
        return

    try:
        deepbrowse_module = importlib.import_module("deepbrowse")
        llm_module = importlib.import_module("deepbrowse.utils.llm")
        browser_module = importlib.import_module("browser_use.browser")

        DeepBrowseAgentSDK = deepbrowse_module.Agent
        _create_llm = llm_module.create_llm
        BrowserProfileSDK = browser_module.BrowserProfile
        BrowserSessionSDK = browser_module.BrowserSession
    except (ImportError, AttributeError) as exc:
        _DEEPBROWSE_IMPORT_ERROR = str(exc)
        logger.error("deepbrowse dependency is not available: %s", exc)


def _get_config_value(agent_config: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in agent_config and agent_config[key] is not None:
            return agent_config[key]
    return default


def _normalize_vision_mode(raw_value: Any) -> str:
    if isinstance(raw_value, bool):
        return "always" if raw_value else "off"
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"always", "auto", "off"}:
            return normalized
    return "auto"


def _coerce_int(raw_value: Any, default: int) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


@register_agent
class DeepBrowseAgent(BaseAgent):
    """Browser automation agent using the DeepBrowse Python SDK."""

    name = "deepbrowse"

    def prepare(self, agent_config: dict[str, Any]) -> None:
        del agent_config
        _load_deepbrowse_dependencies()
        if _DEEPBROWSE_IMPORT_ERROR:
            raise ImportError(
                "deepbrowse dependencies are missing. "
                "Install the deepbrowse checkout first or ensure configs/agent_registry.yaml "
                "install_targets points to a valid local repository."
            )

    def run_task(
        self,
        task_info: dict[str, Any],
        agent_config: dict[str, Any],
        task_workspace: Path,
    ) -> AgentResult:
        self.prepare(agent_config)

        browser_id = _get_config_value(agent_config, "browser_id", "BROWSER_ID", default="Chrome-Local")
        timeout = self.get_timeout(agent_config, 300)
        warn_if_local_proxy_unsupported(agent_config, self.name)

        with open_browser_session(
            browser_id=browser_id,
            agent_name=self.name,
            agent_config=agent_config,
        ) as session_context:
            return asyncio.run(
                self._run_task_async(
                    task_info=task_info,
                    agent_config=agent_config,
                    task_workspace=task_workspace,
                    timeout=timeout,
                    session_context=session_context,
                )
            )

    @staticmethod
    def _resolve_sdk_browser_id(session_context: BrowserSessionContext) -> str:
        if session_context.transport == "local":
            return "Chrome-Local"
        if session_context.transport == "cloud_native" and session_context.backend_id == "browser-use-cloud":
            return "browser-use cloud"
        if session_context.backend_id == "lexmount":
            return "lexmount"
        logger.warning(
            "Unknown DeepBrowse backend mapping, falling back to Chrome-Local: "
            "backend_id=%s transport=%s",
            session_context.backend_id,
            session_context.transport,
        )
        return "Chrome-Local"

    @staticmethod
    def _create_browser_session(
        session_context: BrowserSessionContext,
        agent_config: dict[str, Any],
    ) -> Any:
        if BrowserSessionSDK is None or BrowserProfileSDK is None:
            raise ImportError("deepbrowse browser dependencies are not loaded")

        headless = bool(_get_config_value(agent_config, "headless", "HEADLESS", default=False))
        viewport_width = _coerce_int(
            _get_config_value(
                agent_config,
                "lexmount_viewport_width",
                "LEXMOUNT_VIEWPORT_WIDTH",
                default=1920,
            ),
            1920,
        )
        viewport_height = _coerce_int(
            _get_config_value(
                agent_config,
                "lexmount_viewport_height",
                "LEXMOUNT_VIEWPORT_HEIGHT",
                default=1080,
            ),
            1080,
        )

        if session_context.transport == "cdp":
            if not session_context.cdp_url:
                raise ValueError(f"CDP URL is required for browser id: {session_context.backend_id}")

            browser_kwargs: dict[str, Any] = {
                "headless": headless,
                "cdp_url": session_context.cdp_url,
            }
            if session_context.backend_id == "lexmount":
                browser_kwargs["viewport"] = {
                    "width": viewport_width,
                    "height": viewport_height,
                }
            return BrowserSessionSDK(**browser_kwargs)

        if (
            session_context.transport == "cloud_native"
            and session_context.backend_id == "browser-use-cloud"
        ):
            return BrowserSessionSDK(use_cloud=True)

        if session_context.transport == "local":
            browser_profile = BrowserProfileSDK(
                headless=headless,
                disable_security=bool(
                    _get_config_value(
                        agent_config,
                        "disable_security",
                        "DISABLE_SECURITY",
                        default=True,
                    )
                ),
            )
            return BrowserSessionSDK(browser_profile=browser_profile)

        raise ValueError(
            "Unsupported browser backend for deepbrowse agent: "
            f"backend_id={session_context.backend_id}, transport={session_context.transport}"
        )

    @staticmethod
    async def _close_browser_runtime(browser_session: Any, task_id: str) -> None:
        try:
            await browser_session.stop()
        except (OSError, RuntimeError, TimeoutError) as exc:
            logger.warning("Failed to close DeepBrowse browser session for task %s: %s", task_id, exc)

    @staticmethod
    def _build_usage(raw_usage: dict[str, Any] | None) -> AgentUsage | None:
        if not raw_usage:
            return None
        prompt_tokens = _coerce_int(raw_usage.get("input_tokens"), 0)
        completion_tokens = _coerce_int(raw_usage.get("output_tokens"), 0)
        total_tokens = _coerce_int(raw_usage.get("total_tokens"), prompt_tokens + completion_tokens)
        model_id = raw_usage.get("model_id")
        by_model = None
        if model_id:
            by_model = {
                str(model_id): {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
            }
        return AgentUsage(
            total_prompt_tokens=prompt_tokens,
            total_completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            entry_count=1 if total_tokens else 0,
            by_model=by_model,
        )

    async def _run_task_async(
        self,
        task_info: dict[str, Any],
        agent_config: dict[str, Any],
        task_workspace: Path,
        timeout: int,
        session_context: BrowserSessionContext,
    ) -> AgentResult:
        if DeepBrowseAgentSDK is None or _create_llm is None:
            raise ImportError("deepbrowse SDK is not loaded")

        task_id = str(task_info.get("task_id", "unknown"))
        task_prompt = self.build_task_prompt(task_info)
        model_type = str(_get_config_value(agent_config, "model_type", "MODEL_TYPE", default="OPENAI")).upper()
        model_id = str(_get_config_value(agent_config, "model_id", "MODEL_ID", default=""))
        api_key = self.get_api_key(agent_config)
        base_url = self.get_base_url(agent_config)
        browser_id = _get_config_value(agent_config, "browser_id", "BROWSER_ID", default="Chrome-Local")
        max_steps = self.get_max_steps(agent_config, 50)
        max_action_history_steps = _coerce_int(
            _get_config_value(
                agent_config,
                "max_action_history_steps",
                "MAX_ACTION_HISTORY_STEPS",
                default=10,
            ),
            10,
        )
        keep_last_n_rounds = _coerce_int(
            _get_config_value(agent_config, "keep_last_n_rounds", "KEEP_LAST_N_ROUNDS", default=0),
            0,
        )
        enable_dom_retry = bool(
            _get_config_value(agent_config, "enable_dom_retry", "ENABLE_DOM_RETRY", default=False)
        )
        enable_api_tool = bool(
            _get_config_value(agent_config, "enable_api_tool", "ENABLE_API_TOOL", default=False)
        )
        enable_network_recording = bool(
            _get_config_value(
                agent_config,
                "enable_network_recording",
                "ENABLE_NETWORK_RECORDING",
                default=True,
            )
        )
        debug_artifacts = bool(
            _get_config_value(agent_config, "debug_artifacts", "DEBUG_ARTIFACTS", default=True)
        )
        vision_mode = _normalize_vision_mode(
            _get_config_value(agent_config, "use_vision", "USE_VISION", default="auto")
        )

        config_info = {
            "model_type": model_type,
            "timeout_seconds": timeout,
            "max_steps": max_steps,
            "max_action_history_steps": max_action_history_steps,
            "keep_last_n_rounds": keep_last_n_rounds,
            "enable_dom_retry": enable_dom_retry,
            "enable_api_tool": enable_api_tool,
            "enable_network_recording": enable_network_recording,
            "use_vision": vision_mode,
            "debug_artifacts": debug_artifacts,
        }

        llm = _create_llm(
            model_type=model_type,
            model_id=model_id,
            api_key=api_key,
            base_url=base_url,
        )
        browser_session = self._create_browser_session(session_context, agent_config)
        await browser_session.start()

        agent = DeepBrowseAgentSDK(
            task=task_prompt,
            llm=llm,
            browser=browser_session,
            browser_id=self._resolve_sdk_browser_id(session_context),
            headless=bool(_get_config_value(agent_config, "headless", "HEADLESS", default=False)),
            debug=debug_artifacts,
            screenshots_dir=task_workspace,
            use_vision=vision_mode,
            max_steps=max_steps,
            max_time_seconds=timeout,
            max_action_history_steps=max_action_history_steps,
            keep_last_n_rounds=keep_last_n_rounds,
            enable_dom_retry=enable_dom_retry,
            enable_api_tool=enable_api_tool,
            enable_network_recording=enable_network_recording,
        )

        history = None
        error_msg: str | None = None
        final_answer = ""
        timed_out = False
        start_time = time.time()

        try:
            history = await asyncio.wait_for(agent.run(), timeout=timeout)
            final_answer = (history.final_result() or "").strip()
        except TimeoutError:
            timed_out = True
            error_msg = f"Timeout after {timeout} seconds"
            final_answer = f"[Task Failed: {error_msg}]"
            logger.error("Task %s timed out after %s seconds", task_id, timeout)
        except (RuntimeError, OSError, TypeError, ValueError) as exc:
            error_msg = str(exc)
            final_answer = f"[Task Failed: {error_msg}]"
            logger.error("Task %s execution error: %s", task_id, exc)
        finally:
            await self._close_browser_runtime(browser_session=browser_session, task_id=task_id)

        end_to_end_ms = int((time.time() - start_time) * 1000)
        action_history: list[str] = []
        screenshots: list[str] = []
        steps_count = 0
        usage = None

        if history is not None:
            history_items = (
                history.action_history()
                if hasattr(history, "action_history")
                else history.extracted_content()
            )
            action_history = [str(item) for item in history_items or []]
            screenshots = [Path(path).name for path in history.screenshots() or []]
            steps_count = history.number_of_steps()
            usage = self._build_usage(getattr(history, "usage", None))
            if not final_answer:
                final_answer = (history.final_result() or "").strip()

        agent_success: bool | None = None
        if timed_out:
            env_status = "success"
            agent_done = "timeout"
        elif error_msg:
            env_status = "failed"
            agent_done = "error"
        elif final_answer:
            env_status = "success"
            agent_done = "done"
            agent_success = True
        else:
            env_status = "success"
            agent_done = "max_steps"

        return AgentResult(
            task_id=task_id,
            task=task_prompt,
            timestamp=datetime.now(UTC),
            env_status=env_status,  # type: ignore[arg-type]
            agent_done=agent_done,  # type: ignore[arg-type]
            agent_success=agent_success,
            answer=final_answer,
            error=error_msg,
            model_id=model_id,
            browser_id=str(browser_id),
            action_history=action_history,
            screenshots=screenshots,
            metrics=AgentMetrics(
                end_to_end_ms=end_to_end_ms,
                steps=steps_count,
                usage=usage,
            ),
            config=config_info,
        )
