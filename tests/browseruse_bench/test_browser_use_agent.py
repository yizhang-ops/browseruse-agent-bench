"""Tests for browser-use agent session abstraction integration."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

from browseruse_bench.agents import browser_use as browser_use_module
from browseruse_bench.agents.browser_use import BrowserUseAgent
from browseruse_bench.browsers.types import BrowserSessionContext


def test_run_task_uses_backend_manager_session_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: Dict[str, Any] = {}

    @contextmanager
    def fake_open_browser_session(
        browser_id: str,
        agent_name: str,
        agent_config: Dict[str, Any],
    ) -> Iterator[BrowserSessionContext]:
        captured["browser_id"] = browser_id
        captured["agent_name"] = agent_name
        captured["agent_config"] = agent_config
        yield BrowserSessionContext(
            backend_id="agentbay",
            transport="cdp",
            cdp_url="wss://agentbay.example/cdp",
        )

    async def fake_run_task_async(
        self: BrowserUseAgent,
        task_info: Dict[str, Any],
        task_workspace: Path,
        timeout: int,
        flash_mode: bool,
        agent_config: Dict[str, Any],
        session_context: BrowserSessionContext,
    ) -> Dict[str, Any]:
        captured["session_context"] = session_context
        captured["timeout"] = timeout
        captured["flash_mode"] = flash_mode
        return {
            "task_id": task_info["task_id"],
            "status": "success",
            "answer": "ok",
            "metrics": {},
            "browser_id": session_context.backend_id,
        }

    monkeypatch.setattr(browser_use_module, "open_browser_session", fake_open_browser_session)
    monkeypatch.setattr(BrowserUseAgent, "_run_task_async", fake_run_task_async)

    result = BrowserUseAgent().run_task(
        task_info={"task_id": "t1", "task_text": "open", "url": "https://example.com"},
        agent_config={"BROWSER_ID": "agentbay", "FLASH_MODE": False, "timeout_seconds": 120},
        task_workspace=tmp_path,
    )

    assert result["status"] == "success"
    assert result["browser_id"] == "agentbay"
    assert captured["browser_id"] == "agentbay"
    assert captured["agent_name"] == "browser-use"
    assert captured["timeout"] == 120
    assert captured["flash_mode"] is False
    assert captured["session_context"].cdp_url == "wss://agentbay.example/cdp"


def test_run_task_rejects_unknown_backend(tmp_path: Path) -> None:
    agent = BrowserUseAgent()
    with pytest.raises(ValueError, match="Unknown browser backend"):
        agent.run_task(
            task_info={"task_id": "t1", "task_text": "open", "url": "https://example.com"},
            agent_config={"BROWSER_ID": "not-exists"},
            task_workspace=tmp_path,
        )


def test_create_browser_instance_rejects_cloud_transport_for_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported browser backend for browser-use agent"):
        BrowserUseAgent._create_browser_instance(
            session_context=BrowserSessionContext(
                backend_id="skyvern-cloud",
                transport="cloud_native",
            )
        )


def test_close_browser_runtime_supports_stop() -> None:
    class FakeBrowser:
        def __init__(self) -> None:
            self.stop_calls = 0

        async def stop(self) -> None:
            self.stop_calls += 1

    browser = FakeBrowser()
    asyncio.run(BrowserUseAgent._close_browser_runtime(browser=browser, task_id="t-sync"))
    assert browser.stop_calls == 1


def test_close_browser_runtime_tolerates_close_error() -> None:
    class BrokenBrowser:
        async def stop(self) -> None:
            raise OSError("close failed")

    asyncio.run(BrowserUseAgent._close_browser_runtime(browser=BrokenBrowser(), task_id="t-error"))


def test_run_task_async_tolerates_temp_dir_cleanup_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeAgent:
        def __init__(self, **_: Any) -> None:
            pass

        async def run(self, max_steps: int) -> None:
            del max_steps
            return None

    class FakeBrowser:
        async def stop(self) -> None:
            return None

    class BrokenTempDir:
        def cleanup(self) -> None:
            raise OSError("cleanup failed")

    monkeypatch.setattr(browser_use_module, "Agent", FakeAgent)
    monkeypatch.setattr(
        BrowserUseAgent,
        "_create_browser_instance",
        staticmethod(lambda session_context: (FakeBrowser(), BrokenTempDir())),
    )
    monkeypatch.setattr(
        BrowserUseAgent,
        "_create_llm",
        lambda self, model_type, model_id, agent_config, config_info: object(),
    )
    caplog.set_level("WARNING")

    result = asyncio.run(
        BrowserUseAgent()._run_task_async(
            task_info={"task_id": "t-cleanup", "task_text": "open page", "url": "https://example.com"},
            task_workspace=tmp_path,
            timeout=1,
            flash_mode=False,
            agent_config={"MODEL_TYPE": "OPENAI", "MODEL_ID": "gpt-test"},
            session_context=BrowserSessionContext(backend_id="Chrome-Local", transport="local"),
        )
    )

    assert result.env_status.value == "success"
    assert any("Failed to cleanup temporary directory" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# local_proxy → BrowserUseProxySettings → Browser kwargs
# ---------------------------------------------------------------------------


def test_create_browser_instance_passes_local_proxy_to_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Dict[str, Any] = {}

    class FakeBrowser:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(browser_use_module, "Browser", FakeBrowser)

    ctx = BrowserSessionContext(
        backend_id="local",
        transport="local",
        metadata={
            "local_proxy": {
                "server": "http://127.0.0.1:7890",
                "username": "alice",
                "password": "s3cr3t",
                "bypass": "127.0.0.1,localhost",
            }
        },
    )
    _, temp_dir = BrowserUseAgent._create_browser_instance(session_context=ctx)
    try:
        proxy = captured["proxy"]
        # ProxySettings is a pydantic model; access is attribute-based.
        assert proxy.server == "http://127.0.0.1:7890"
        assert proxy.username == "alice"
        assert proxy.password == "s3cr3t"
        assert proxy.bypass == "127.0.0.1,localhost"
        assert captured["headless"] is False
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def test_create_browser_instance_no_proxy_omits_kwarg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Dict[str, Any] = {}

    class FakeBrowser:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(browser_use_module, "Browser", FakeBrowser)

    ctx = BrowserSessionContext(backend_id="local", transport="local")
    _, temp_dir = BrowserUseAgent._create_browser_instance(session_context=ctx)
    try:
        assert "proxy" not in captured
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
