from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class BrowserSessionContext:
    """Unified browser session context shared by agent implementations."""

    backend_id: str
    transport: str
    cdp_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

