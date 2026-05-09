"""Tests for DeepBrowse agent session abstraction integration."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from browseruse_bench.agents import deepbrowse as deepbrowse_module
from browseruse_bench.agents.deepbrowse import DeepBrowseAgent
from browseruse_bench.browsers.types import BrowserSessionContext


def test_run_task_uses_backend_manager_session_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    @contextmanager
    def fake_open_browser_session(
        browser_id: str,
        agent_name: str,
        agent_config: dict[str, Any],
    ) -> Iterator[BrowserSessionContext]:
        captured["browser_id"] = browser_id
        captured["agent_name"] = agent_name
        captured["agent_config"] = agent_config
        yield BrowserSessionContext(
            backend_id="lexmount",
            transport="cdp",
            cdp_url="wss://lexmount.example/cdp",
        )

    async def fake_run_task_async(
        self: DeepBrowseAgent,
        task_info: dict[str, Any],
        agent_config: dict[str, Any],
        task_workspace: Path,
        timeout: int,
        session_context: BrowserSessionContext,
    ) -> dict[str, Any]:
        del self, task_workspace
        captured["task_info"] = task_info
        captured["agent_config_async"] = agent_config
        captured["timeout"] = timeout
        captured["session_context"] = session_context
        return {
            "task_id": task_info["task_id"],
            "status": "success",
            "answer": "ok",
            "metrics": {},
        }

    monkeypatch.setattr(deepbrowse_module, "open_browser_session", fake_open_browser_session)
    monkeypatch.setattr(DeepBrowseAgent, "prepare", lambda self, agent_config: None)
    monkeypatch.setattr(DeepBrowseAgent, "_run_task_async", fake_run_task_async)

    result = DeepBrowseAgent().run_task(
        task_info={"task_id": "t1", "task_text": "open", "url": "https://example.com"},
        agent_config={"browser_id": "lexmount", "timeout_seconds": 120},
        task_workspace=tmp_path,
    )

    assert result["status"] == "success"
    assert captured["browser_id"] == "lexmount"
    assert captured["agent_name"] == "deepbrowse"
    assert captured["timeout"] == 120
    assert captured["session_context"].cdp_url == "wss://lexmount.example/cdp"


def test_create_browser_session_rejects_unknown_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBrowserSession:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

    class FakeBrowserProfile:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

    monkeypatch.setattr(deepbrowse_module, "BrowserSessionSDK", FakeBrowserSession)
    monkeypatch.setattr(deepbrowse_module, "BrowserProfileSDK", FakeBrowserProfile)

    with pytest.raises(ValueError, match="Unsupported browser backend for deepbrowse agent"):
        DeepBrowseAgent._create_browser_session(
            session_context=BrowserSessionContext(
                backend_id="skyvern-cloud",
                transport="cloud_native",
            ),
            agent_config={},
        )


def test_close_browser_runtime_tolerates_close_error() -> None:
    class BrokenBrowserSession:
        async def stop(self) -> None:
            raise OSError("close failed")

    asyncio.run(
        DeepBrowseAgent._close_browser_runtime(
            browser_session=BrokenBrowserSession(),
            task_id="t-error",
        )
    )


def test_build_usage_tolerates_missing_model_id() -> None:
    usage = DeepBrowseAgent._build_usage({"input_tokens": 10, "output_tokens": 2})

    assert usage is not None
    assert usage.total_prompt_tokens == 10
    assert usage.total_completion_tokens == 2
    assert usage.total_tokens == 12
    assert usage.by_model is None


def test_run_task_prefers_agent_history_action_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = DeepBrowseAgent()

    class FakeHistory:
        def final_result(self) -> str:
            return "done"

        def action_history(self) -> list[str]:
            return ["Clicked Search"]

        def extracted_content(self) -> list[str]:
            return ["legacy content"]

        def screenshots(self) -> list[str]:
            return []

        def number_of_steps(self) -> int:
            return 1

        @property
        def usage(self):  # noqa: ANN201
            return None

    class FakeBrowserSession:
        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    class FakeAgentRuntime:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        async def run(self) -> FakeHistory:
            return FakeHistory()

    monkeypatch.setattr(deepbrowse_module, "DeepBrowseAgentSDK", FakeAgentRuntime)
    monkeypatch.setattr(deepbrowse_module, "_create_llm", lambda **kwargs: object())
    monkeypatch.setattr(DeepBrowseAgent, "_create_browser_session", lambda *_args, **_kwargs: FakeBrowserSession())

    result = asyncio.run(
        agent._run_task_async(
            task_info={"task_id": "t-history", "task_text": "open"},
            agent_config={"browser_id": "Chrome-Local", "timeout_seconds": 10},
            task_workspace=tmp_path,
            timeout=10,
            session_context=BrowserSessionContext(
                backend_id="chrome-local",
                transport="cdp",
                cdp_url="ws://example.test/devtools",
            ),
        )
    )

    assert result.action_history == ["Clicked Search"]
