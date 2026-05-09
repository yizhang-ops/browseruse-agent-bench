from __future__ import annotations

from typing import Callable, Dict

from browseruse_bench.browsers.base import BrowserBackend

_BACKEND_FACTORIES: Dict[str, Callable[[], BrowserBackend]] = {}
_DEFAULTS_REGISTERED = False


def _create_local_backend(browser_id: str) -> BrowserBackend:
    from browseruse_bench.browsers.providers.local import LocalBackend

    return LocalBackend(browser_id)


def _create_cloud_native_backend(browser_id: str) -> BrowserBackend:
    from browseruse_bench.browsers.providers.cloudnative import CloudNativeBackend

    return CloudNativeBackend(browser_id)


def _create_cdp_backend() -> BrowserBackend:
    from browseruse_bench.browsers.providers.cloudnative import CDPBackend

    return CDPBackend("cdp")


def _create_lexmount_backend() -> BrowserBackend:
    from browseruse_bench.browsers.providers.lexmount import LexmountBackend

    return LexmountBackend("lexmount")


def _create_agentbay_backend() -> BrowserBackend:
    from browseruse_bench.browsers.providers.agentbay import AgentBayBackend

    return AgentBayBackend("agentbay")


def register_backend(browser_id: str, factory: Callable[[], BrowserBackend]) -> None:
    if browser_id in _BACKEND_FACTORIES:
        raise ValueError(f"Browser backend already registered: {browser_id}")
    _BACKEND_FACTORIES[browser_id] = factory


def _register_default_backends() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return

    register_backend("Chrome-Local", lambda: _create_local_backend("Chrome-Local"))
    register_backend("local", lambda: _create_local_backend("local"))
    register_backend("browser-use-cloud", lambda: _create_cloud_native_backend("browser-use-cloud"))
    register_backend("skyvern-cloud", lambda: _create_cloud_native_backend("skyvern-cloud"))
    register_backend("cdp", _create_cdp_backend)
    register_backend("lexmount", _create_lexmount_backend)
    register_backend("agentbay", _create_agentbay_backend)
    _DEFAULTS_REGISTERED = True


def get_backend(browser_id: str) -> BrowserBackend:
    _register_default_backends()
    factory = _BACKEND_FACTORIES.get(browser_id)
    if factory is None:
        available = ", ".join(sorted(_BACKEND_FACTORIES.keys()))
        raise ValueError(f"Unknown browser backend: '{browser_id}'. Available: {available}")
    return factory()
