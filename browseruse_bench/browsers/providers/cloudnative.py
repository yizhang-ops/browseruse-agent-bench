from __future__ import annotations

from typing import Any, Dict

from browseruse_bench.browsers.base import BrowserBackend
from browseruse_bench.browsers.types import BrowserSessionContext


class CloudNativeBackend(BrowserBackend):
    """Cloud-managed backend for SDK-hosted browser sessions.

    This backend is for platforms that host browser sessions on their side
    (for example, browser-use-cloud and skyvern-cloud), so benchmark code
    only carries backend identity and transport metadata.
    """

    def __init__(self, backend_id: str) -> None:
        super().__init__(backend_id)

    def open(self, agent_name: str, agent_config: Dict[str, Any]) -> BrowserSessionContext:
        return BrowserSessionContext(
            backend_id=self.backend_id,
            transport="cloud_native",
        )

    def close(self, session_context: BrowserSessionContext) -> None:
        return None


class CDPBackend(BrowserBackend):
    """External CDP browser backend."""

    def __init__(self, backend_id: str) -> None:
        super().__init__(backend_id)

    def open(self, agent_name: str, agent_config: Dict[str, Any]) -> BrowserSessionContext:
        cdp_address = str(agent_config.get("CDP_ADDRESS") or "http://localhost:9222")
        return BrowserSessionContext(
            backend_id=self.backend_id,
            transport="cdp",
            cdp_url=cdp_address,
        )

    def close(self, session_context: BrowserSessionContext) -> None:
        return None
