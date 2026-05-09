"""Tests for browseruse_bench.agents.registry module."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

from browseruse_bench.agents import registry as registry_module
from browseruse_bench.agents.base import BaseAgent


@pytest.fixture(autouse=True)
def restore_registry_state() -> Iterator[None]:
    """Keep global registry isolated across tests."""
    original = dict(registry_module._AGENT_REGISTRY)
    registry_module._AGENT_REGISTRY.clear()
    try:
        yield
    finally:
        registry_module._AGENT_REGISTRY.clear()
        registry_module._AGENT_REGISTRY.update(original)


def test_register_agent_rejects_duplicate_name_conflict() -> None:
    class FirstAgent(BaseAgent):
        name = "dup-agent"

        def run_task(
            self, task_info: Dict[str, Any], agent_config: Dict[str, Any], task_workspace: Path
        ) -> Dict[str, Any]:
            return {}

    class SecondAgent(BaseAgent):
        name = "dup-agent"

        def run_task(
            self, task_info: Dict[str, Any], agent_config: Dict[str, Any], task_workspace: Path
        ) -> Dict[str, Any]:
            return {}

    registry_module.register_agent(FirstAgent)

    with pytest.raises(ValueError, match="Agent name conflict"):
        registry_module.register_agent(SecondAgent)


def test_register_agent_allows_idempotent_registration() -> None:
    class StableAgent(BaseAgent):
        name = "stable-agent"

        def run_task(
            self, task_info: Dict[str, Any], agent_config: Dict[str, Any], task_workspace: Path
        ) -> Dict[str, Any]:
            return {"status": "ok"}

    registry_module.register_agent(StableAgent)
    registry_module.register_agent(StableAgent)

    assert registry_module.list_agents() == ["stable-agent"]
    assert registry_module._AGENT_REGISTRY["stable-agent"] is StableAgent


def test_get_agent_returns_registered_instance() -> None:
    class DemoAgent(BaseAgent):
        name = "demo-agent"

        def run_task(
            self, task_info: Dict[str, Any], agent_config: Dict[str, Any], task_workspace: Path
        ) -> Dict[str, Any]:
            return {"task_id": "x", "status": "success", "answer": "ok", "metrics": {}}

    registry_module.register_agent(DemoAgent)

    instance = registry_module.get_agent("demo-agent")
    assert isinstance(instance, DemoAgent)
