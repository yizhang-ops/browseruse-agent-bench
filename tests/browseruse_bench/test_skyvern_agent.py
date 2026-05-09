"""Tests for Skyvern agent runtime cleanup boundaries."""

from __future__ import annotations

import asyncio

from browseruse_bench.agents.skyvern import SkyvernAgent, _build_local_chromium_args


def test_close_runtime_resources_closes_browser_and_client() -> None:
    state = {"browser_close_calls": 0, "client_close_calls": 0}

    class FakeBrowser:
        async def close(self) -> None:
            state["browser_close_calls"] += 1

    class FakeSkyvernClient:
        async def aclose(self) -> None:
            state["client_close_calls"] += 1

    agent = SkyvernAgent()
    asyncio.run(
        agent._close_runtime_resources(
            browser=FakeBrowser(),
            skyvern_client=FakeSkyvernClient(),
            task_id="task-1",
        )
    )

    assert state["browser_close_calls"] == 1
    assert state["client_close_calls"] == 1


def test_close_runtime_resources_tolerates_close_errors() -> None:
    class BrokenBrowser:
        async def close(self) -> None:
            raise OSError("browser close failed")

    class BrokenSkyvernClient:
        async def aclose(self) -> None:
            raise RuntimeError("client close failed")

    agent = SkyvernAgent()
    asyncio.run(
        agent._close_runtime_resources(
            browser=BrokenBrowser(),
            skyvern_client=BrokenSkyvernClient(),
            task_id="task-2",
        )
    )


# ---------------------------------------------------------------------------
# local_proxy → Chrome --proxy-server CLI args
# (Skyvern.launch_local_browser bypasses its own BrowserFactory, so we must
# inject proxy via Chrome flags rather than Skyvern's ENABLE_PROXY env vars.)
# ---------------------------------------------------------------------------


def test_build_local_chromium_args_no_proxy() -> None:
    assert _build_local_chromium_args({}, None) == []
    assert _build_local_chromium_args({}, {}) == []
    assert _build_local_chromium_args({}, {"server": ""}) == []
    assert _build_local_chromium_args({}, {"server": "   "}) == []


def test_build_local_chromium_args_server_only() -> None:
    args = _build_local_chromium_args({}, {"server": "http://127.0.0.1:7897"})
    assert args == ["--proxy-server=http://127.0.0.1:7897"]


def test_build_local_chromium_args_with_auth() -> None:
    args = _build_local_chromium_args(
        {},
        {
            "server": "http://proxy.corp:3128",
            "username": "alice",
            "password": "s3cr3t",
        },
    )
    assert args == ["--proxy-server=http://alice:s3cr3t@proxy.corp:3128"]


def test_build_local_chromium_args_quotes_special_chars_in_password() -> None:
    args = _build_local_chromium_args(
        {},
        {"server": "http://proxy:8080", "username": "user@home", "password": "p@ss:word"},
    )
    assert args == ["--proxy-server=http://user%40home:p%40ss%3Aword@proxy:8080"]


def test_build_local_chromium_args_strips_existing_auth_when_explicit_provided() -> None:
    # Explicit username/password win over any auth embedded in the server URL —
    # we must not emit a malformed "alice:s3cret@old:cred@host" netloc.
    args = _build_local_chromium_args(
        {},
        {
            "server": "http://oldUser:oldPass@proxy.corp:3128",
            "username": "alice",
            "password": "s3cr3t",
        },
    )
    assert args == ["--proxy-server=http://alice:s3cr3t@proxy.corp:3128"]


def test_build_local_chromium_args_keeps_embedded_auth_when_no_explicit() -> None:
    args = _build_local_chromium_args(
        {}, {"server": "http://embedded:cred@proxy.corp:3128"}
    )
    assert args == ["--proxy-server=http://embedded:cred@proxy.corp:3128"]


def test_build_local_chromium_args_includes_bypass_list() -> None:
    args = _build_local_chromium_args(
        {},
        {
            "server": "http://127.0.0.1:7897",
            "bypass": "127.0.0.1,localhost,*.local",
        },
    )
    assert args == [
        "--proxy-server=http://127.0.0.1:7897",
        "--proxy-bypass-list=127.0.0.1,localhost,*.local",
    ]


def test_build_local_chromium_args_unparseable_server_returned_as_is() -> None:
    # Defensive: bare "host:port" without scheme — Chrome accepts it; don't mangle.
    args = _build_local_chromium_args(
        {},
        {
            "server": "host:8080",
            "username": "alice",
            "password": "s3cr3t",
        },
    )
    assert args == ["--proxy-server=host:8080"]


def test_build_local_chromium_args_password_without_username_drops_auth() -> None:
    # A bare password (no username) would otherwise produce a malformed
    # ":secret@host" netloc that most proxies reject (RFC 3986 violation).
    # Skip the auth embedding entirely in that case.
    args = _build_local_chromium_args(
        {},
        {
            "server": "http://proxy.corp:3128",
            "password": "s3cr3t",
        },
    )
    assert args == ["--proxy-server=http://proxy.corp:3128"]


def test_build_local_chromium_args_username_only_no_password() -> None:
    # Username only (no password) is RFC-valid: "user@host". Verify we emit it.
    args = _build_local_chromium_args(
        {},
        {
            "server": "http://proxy.corp:3128",
            "username": "alice",
        },
    )
    assert args == ["--proxy-server=http://alice@proxy.corp:3128"]
