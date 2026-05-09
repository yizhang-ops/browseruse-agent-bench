from __future__ import annotations

import logging
import os
import warnings
from typing import Any, Dict

from agentbay import AgentBay as AgentBaySDK
from agentbay import BrowserOption as BrowserOptionSDK
from agentbay import CreateSessionParams as CreateSessionParamsSDK

from browseruse_bench.browsers.base import BrowserBackend
from browseruse_bench.browsers.session_state import clear_session_state, write_session_state
from browseruse_bench.browsers.types import BrowserSessionContext

logger = logging.getLogger(__name__)


_CLEANUP_EXCEPTIONS = (
    ConnectionError,
    OSError,
    RuntimeError,
    TimeoutError,
)


def _resolve_bool_config(value: Any, default: bool, config_key: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False

    logger.warning(
        "Invalid boolean value for %s: %r. Falling back to default=%s",
        config_key,
        value,
        default,
    )
    return default


def _read_agentbay_config(agent_config: Dict[str, Any], snake: str) -> Any:
    """Read an AgentBay config key, preferring snake_case and falling back to legacy UPPERCASE.

    Emits a deprecation warning when a user's config still uses the old UPPERCASE form.
    Uses ``warnings.warn`` so the default filter deduplicates by (message, category,
    module, lineno) — one warning per key per process instead of one per session.
    """
    if snake in agent_config:
        return agent_config[snake]
    upper = snake.upper()
    if upper in agent_config:
        warnings.warn(
            f"AgentBay config key {upper!r} is deprecated; rename it to {snake!r} in config.yaml",
            DeprecationWarning,
            stacklevel=3,
        )
        return agent_config[upper]
    return None


def _cleanup_failed_session_open(agent_bay: Any, session: Any) -> None:
    try:
        delete_result = agent_bay.delete(session)
    except _CLEANUP_EXCEPTIONS as exc:
        logger.error("AgentBay session cleanup after open failure raised an error: %s", exc)
        return

    if delete_result is not None and getattr(delete_result, "success", True) is False:
        error_message = getattr(delete_result, "error_message", "unknown error")
        logger.error("AgentBay session cleanup after open failure failed: %s", error_message)


class AgentBayBackend(BrowserBackend):
    def __init__(self, backend_id: str) -> None:
        super().__init__(backend_id)

    def open(self, agent_name: str, agent_config: Dict[str, Any]) -> BrowserSessionContext:
        api_key = _read_agentbay_config(agent_config, "agentbay_api_key") or os.getenv("AGENTBAY_API_KEY")
        if not api_key:
            raise ValueError(
                "AgentBay requires an API key: set `agentbay_api_key` in config.yaml "
                "(e.g. `agentbay_api_key: $AGENTBAY_API_KEY`) or the AGENTBAY_API_KEY environment variable"
            )

        image_id = str(
            _read_agentbay_config(agent_config, "agentbay_image_id")
            or os.getenv("AGENTBAY_IMAGE_ID")
            or "browser_latest"
        )
        enable_browser_replay = _resolve_bool_config(
            value=_read_agentbay_config(agent_config, "agentbay_enable_browser_replay"),
            default=True,
            config_key="agentbay_enable_browser_replay",
        )
        use_stealth = _resolve_bool_config(
            value=_read_agentbay_config(agent_config, "agentbay_browser_use_stealth"),
            default=False,
            config_key="agentbay_browser_use_stealth",
        )

        logger.info("[INFO] Creating AgentBay cloud browser session...")
        agent_bay = AgentBaySDK(api_key=api_key)
        create_params = CreateSessionParamsSDK(
            image_id=image_id,
            enable_browser_replay=enable_browser_replay,
        )
        create_result = agent_bay.create(create_params)
        if not getattr(create_result, "success", False):
            error_message = getattr(create_result, "error_message", "unknown error")
            raise RuntimeError(f"AgentBay session creation failed: {error_message}")

        session = getattr(create_result, "session", None)
        if session is None:
            raise RuntimeError("AgentBay session creation failed: session is empty")

        cdp_url: str | None = None
        session_opened = False
        try:
            browser_option = BrowserOptionSDK(use_stealth=use_stealth)
            initialized = session.browser.initialize(browser_option)
            if not initialized:
                raise RuntimeError("AgentBay browser initialization failed")

            cdp_url = session.browser.get_endpoint_url()
            if not cdp_url:
                raise RuntimeError("AgentBay endpoint URL is empty")
            session_opened = True
        finally:
            if not session_opened:
                _cleanup_failed_session_open(agent_bay=agent_bay, session=session)

        session_id = str(getattr(session, "session_id", "") or "")
        if session_id:
            write_session_state(backend_id=self.backend_id, session_id=session_id)

        logger.info("[SUCCESS] AgentBay session created: %s...", str(cdp_url)[:50])
        return BrowserSessionContext(
            backend_id=self.backend_id,
            transport="cdp",
            cdp_url=str(cdp_url),
            metadata={
                "agent_bay": agent_bay,
                "session": session,
                "session_id": session_id,
            },
        )

    def close(self, session_context: BrowserSessionContext) -> None:
        agent_bay = session_context.metadata.get("agent_bay")
        session = session_context.metadata.get("session")
        if agent_bay is not None and session is not None:
            try:
                delete_result = agent_bay.delete(session)
            except _CLEANUP_EXCEPTIONS as exc:
                logger.error("AgentBay session cleanup raised an error: %s", exc)
            else:
                if delete_result is not None and getattr(delete_result, "success", True) is False:
                    error_message = getattr(delete_result, "error_message", "unknown error")
                    logger.error("AgentBay session cleanup failed: %s", error_message)

        try:
            clear_session_state()
        except (OSError, RuntimeError) as exc:
            logger.error("Failed to clear browser session state: %s", exc)
