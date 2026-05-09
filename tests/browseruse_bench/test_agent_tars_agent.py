"""Tests for AgentTARSAgent browser session wiring.

Covers the changes that added Lexmount cloud browser support:
- local browser_id  → --headless in CLI args
- cdp/lexmount      → --headless + --browser.cdpEndpoint in CLI args
- default browser_id is "local"
- open_browser_session cleanup runs even when subprocess raises FileNotFoundError
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List

import pytest

import browseruse_bench.agents.agent_tars as agent_tars_module
from browseruse_bench.agents.agent_tars import AgentTARSAgent
from browseruse_bench.browsers.types import BrowserSessionContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _local_port_available() -> None:
    """Skip any test that requires local TCP port binding when the environment
    does not permit it (e.g. some CI sandboxes raise PermissionError on bind)."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.close()
    except OSError as exc:
        pytest.skip(f"Local port binding not permitted in this environment: {exc}")


class _FakeProxyServer:
    """Minimal stand-in for http.server.HTTPServer returned by _start_cdp_proxy_server."""

    def shutdown(self) -> None:
        pass


def _fake_cdp_proxy_factory(port: int = 54321):
    """Return a _start_cdp_proxy_server replacement that never binds a real port."""

    def _fake(wss_url: str) -> tuple[_FakeProxyServer, int]:
        return _FakeProxyServer(), port

    return _fake


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_session_factory(
    transport: str,
    cdp_url: str | None = None,
    *,
    close_tracker: Dict[str, int] | None = None,
) -> Any:
    """Return a monkeypatched open_browser_session that yields a fake context."""

    @contextmanager
    def _fake_open_browser_session(
        browser_id: str,
        agent_name: str,
        agent_config: Dict[str, Any],
    ) -> Generator[BrowserSessionContext, None, None]:
        try:
            yield BrowserSessionContext(
                backend_id=browser_id,
                transport=transport,
                cdp_url=cdp_url,
            )
        finally:
            if close_tracker is not None:
                close_tracker["calls"] = close_tracker.get("calls", 0) + 1

    return _fake_open_browser_session


def _make_agent_and_config(browser_id: str | None = None) -> tuple[AgentTARSAgent, Dict[str, Any]]:
    agent_config: Dict[str, Any] = {
        "model_provider": "openai",
        "model_id": "gpt-test",
        "api_key": "sk-test",
        "browser_control": "hybrid",
        "timeout_seconds": 10,
    }
    if browser_id is not None:
        agent_config["browser_id"] = browser_id
    return AgentTARSAgent(), agent_config


def _make_task_info() -> Dict[str, Any]:
    return {
        "task_id": "t001",
        "task_text": "click the button",
        "url": "https://example.com",
    }


def _captured_run_subprocess(captured: Dict[str, Any], returncode: int = 0) -> Any:
    """Return a _run_subprocess replacement that records full_cmd and returns success."""

    def _fake(self: Any, cmd: List[str], *, timeout: int, task_workspace: Path, **kwargs: Any) -> tuple:
        captured["cmd"] = cmd
        return returncode, [], None

    return _fake


# ---------------------------------------------------------------------------
# Tests: CLI arg generation based on browser transport
# ---------------------------------------------------------------------------

class TestBrowserTransportCliArgs:
    def test_local_transport_adds_headless_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured: Dict[str, Any] = {}
        monkeypatch.setattr(
            agent_tars_module, "open_browser_session", _fake_session_factory("local")
        )
        monkeypatch.setattr(AgentTARSAgent, "_run_subprocess", _captured_run_subprocess(captured))

        agent, agent_config = _make_agent_and_config(browser_id="local")
        agent.run_task(_make_task_info(), agent_config, tmp_path)

        assert "--headless" in captured["cmd"]
        assert "--browser.cdpEndpoint" not in captured["cmd"]

    def test_cdp_transport_adds_cdp_endpoint_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cdp_url = "wss://cdp.lexmount.test/devtools/browser/abc"
        captured: Dict[str, Any] = {}
        monkeypatch.setattr(
            agent_tars_module,
            "open_browser_session",
            _fake_session_factory("cdp", cdp_url=cdp_url),
        )
        monkeypatch.setattr(AgentTARSAgent, "_run_subprocess", _captured_run_subprocess(captured))
        # Prevent real port binding so the test passes in restricted environments.
        _fake_port = 54321
        monkeypatch.setattr(
            agent_tars_module, "_start_cdp_proxy_server", _fake_cdp_proxy_factory(_fake_port)
        )

        agent, agent_config = _make_agent_and_config(browser_id="lexmount")
        agent.run_task(_make_task_info(), agent_config, tmp_path)

        # --headless is always present (CLI non-interactive mode flag)
        assert "--headless" in captured["cmd"]
        cdp_idx = captured["cmd"].index("--browser.cdpEndpoint")
        endpoint = captured["cmd"][cdp_idx + 1]
        # Agent-TARS expects an HTTP /json/version URL — we wrap the wss:// URL
        # in a local proxy rather than passing the WebSocket URL directly.
        assert endpoint == f"http://127.0.0.1:{_fake_port}/json/version"

    def test_cdp_transport_without_url_falls_back_to_headless(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # transport=cdp but cdp_url is None → fall back to --headless
        captured: Dict[str, Any] = {}
        monkeypatch.setattr(
            agent_tars_module,
            "open_browser_session",
            _fake_session_factory("cdp", cdp_url=None),
        )
        monkeypatch.setattr(AgentTARSAgent, "_run_subprocess", _captured_run_subprocess(captured))

        agent, agent_config = _make_agent_and_config(browser_id="cdp")
        agent.run_task(_make_task_info(), agent_config, tmp_path)

        assert "--headless" in captured["cmd"]
        assert "--browser.cdpEndpoint" not in captured["cmd"]

    def test_default_browser_id_is_local(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        open_calls: Dict[str, Any] = {}

        @contextmanager
        def _recording_open_session(
            browser_id: str, agent_name: str, agent_config: Dict[str, Any]
        ) -> Generator[BrowserSessionContext, None, None]:
            open_calls["browser_id"] = browser_id
            yield BrowserSessionContext(backend_id=browser_id, transport="local")

        monkeypatch.setattr(agent_tars_module, "open_browser_session", _recording_open_session)
        monkeypatch.setattr(
            AgentTARSAgent, "_run_subprocess", _captured_run_subprocess({})
        )

        agent, agent_config = _make_agent_and_config(browser_id=None)  # no browser_id key
        agent.run_task(_make_task_info(), agent_config, tmp_path)

        assert open_calls["browser_id"] == "local"


# ---------------------------------------------------------------------------
# Tests: browser session cleanup
# ---------------------------------------------------------------------------

class TestBrowserSessionCleanup:
    def test_session_cleanup_runs_after_file_not_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        close_tracker: Dict[str, int] = {}

        monkeypatch.setattr(
            agent_tars_module,
            "open_browser_session",
            _fake_session_factory("local", close_tracker=close_tracker),
        )

        def _raise_file_not_found(
            self: Any, cmd: List[str], *, timeout: int, task_workspace: Path, **kwargs: Any
        ) -> tuple:
            raise FileNotFoundError("agent-tars not found")

        monkeypatch.setattr(AgentTARSAgent, "_run_subprocess", _raise_file_not_found)

        agent, agent_config = _make_agent_and_config(browser_id="local")
        result = agent.run_task(_make_task_info(), agent_config, tmp_path)

        # FileNotFoundError is caught inside run_task; agent returns an error result
        assert result.env_status == "failed"  # type: ignore[union-attr]
        # Session context manager __exit__ ran exactly once
        assert close_tracker.get("calls", 0) == 1

    def test_session_cleanup_runs_on_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        close_tracker: Dict[str, int] = {}

        monkeypatch.setattr(
            agent_tars_module,
            "open_browser_session",
            _fake_session_factory("local", close_tracker=close_tracker),
        )
        monkeypatch.setattr(AgentTARSAgent, "_run_subprocess", _captured_run_subprocess({}))

        agent, agent_config = _make_agent_and_config(browser_id="local")
        agent.run_task(_make_task_info(), agent_config, tmp_path)

        assert close_tracker.get("calls", 0) == 1


# ---------------------------------------------------------------------------
# Tests: CDP proxy server
# ---------------------------------------------------------------------------

class TestCDPProxyServer:
    @pytest.fixture(autouse=True)
    def _require_port_binding(self, _local_port_available: None) -> None:
        """Skip all tests in this class if local port binding is not permitted."""

    def test_proxy_serves_json_version(self) -> None:
        import json
        import urllib.request

        from browseruse_bench.agents.agent_tars import _start_cdp_proxy_server

        wss_url = "wss://api.lexmount.cn/devtools/browser/test-uuid?session_id=abc123"
        server, port = _start_cdp_proxy_server(wss_url)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version")
            data = json.loads(resp.read())
            assert data["webSocketDebuggerUrl"] == wss_url
        finally:
            server.shutdown()

    def test_proxy_uses_random_free_port(self) -> None:
        from browseruse_bench.agents.agent_tars import _start_cdp_proxy_server

        server1, port1 = _start_cdp_proxy_server("wss://example.com/1")
        server2, port2 = _start_cdp_proxy_server("wss://example.com/2")
        try:
            assert port1 != port2
        finally:
            server1.shutdown()
            server2.shutdown()


# ---------------------------------------------------------------------------
# Tests: native CDP (http://) pass-through and proxy error handling
# ---------------------------------------------------------------------------

class TestNativeCDPAndProxyErrors:
    def test_http_cdp_url_passed_directly_without_proxy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """http:// CDP URL (native Chrome DevTools) must be forwarded as-is."""
        cdp_url = "http://localhost:9222"
        captured: Dict[str, Any] = {}
        monkeypatch.setattr(
            agent_tars_module,
            "open_browser_session",
            _fake_session_factory("cdp", cdp_url=cdp_url),
        )
        monkeypatch.setattr(AgentTARSAgent, "_run_subprocess", _captured_run_subprocess(captured))

        agent, agent_config = _make_agent_and_config(browser_id="cdp")
        agent.run_task(_make_task_info(), agent_config, tmp_path)

        assert "--browser.cdpEndpoint" in captured["cmd"]
        idx = captured["cmd"].index("--browser.cdpEndpoint")
        assert captured["cmd"][idx + 1] == cdp_url  # direct, no proxy wrapper

    def test_proxy_os_error_returns_failed_agent_result(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """OSError/PermissionError from _start_cdp_proxy_server is caught and
        returned as a failed AgentResult instead of bubbling up."""
        monkeypatch.setattr(
            agent_tars_module,
            "open_browser_session",
            _fake_session_factory("cdp", cdp_url="wss://example.com/browser/test"),
        )

        def _raise_permission_error(wss_url: str) -> None:
            raise PermissionError("[Errno 1] Operation not permitted")

        monkeypatch.setattr(agent_tars_module, "_start_cdp_proxy_server", _raise_permission_error)

        agent, agent_config = _make_agent_and_config(browser_id="lexmount")
        result = agent.run_task(_make_task_info(), agent_config, tmp_path)

        assert result.env_status == "failed"  # type: ignore[union-attr]
        assert result.error is not None  # type: ignore[union-attr]
        assert "CDP proxy" in result.error  # type: ignore[union-attr]
