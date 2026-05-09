from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator

from browseruse_bench.browsers.registry import get_backend
from browseruse_bench.browsers.types import BrowserSessionContext

logger = logging.getLogger(__name__)


@contextmanager
def open_browser_session(
    browser_id: str,
    agent_name: str,
    agent_config: Dict[str, Any],
) -> Iterator[BrowserSessionContext]:
    """Manage backend session lifecycle for browser agents.

    Ownership boundary:
    - This context manager always closes backend sessions via `backend.close(...)`.
    - Agents should only close their SDK/browser runtime objects in agent code.
    """
    backend = get_backend(browser_id)
    session_context = backend.open(agent_name=agent_name, agent_config=agent_config)
    try:
        yield session_context
    finally:
        try:
            backend.close(session_context)
        except (
            ConnectionError,
            OSError,
            RuntimeError,
            TimeoutError,
        ) as exc:
            logger.error(
                "Browser backend cleanup failed (backend=%s, agent=%s): %s",
                session_context.backend_id,
                agent_name,
                exc,
            )
