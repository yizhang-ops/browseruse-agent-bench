from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from browseruse_bench.browsers.types import BrowserSessionContext


class BrowserBackend(ABC):
    """Backend contract for opening/closing browser sessions."""


    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id

    @abstractmethod
    def open(self, agent_name: str, agent_config: Dict[str, Any]) -> BrowserSessionContext:
        pass

    @abstractmethod
    def close(self, session_context: BrowserSessionContext) -> None:
        pass
