"""
Agent Registry - Central registry for all agent implementations.

Provides functions to register, list, and retrieve agent instances.
"""

from __future__ import annotations

from browseruse_bench.agents.base import BaseAgent

# Global registry of agent classes
_AGENT_REGISTRY: dict[str, type[BaseAgent]] = {}


def register_agent(agent_class: type[BaseAgent]) -> type[BaseAgent]:
    """
    Decorator to register an agent class.

    Usage:
        @register_agent
        class MyAgent(BaseAgent):
            name = "my-agent"
            ...
    """
    if not hasattr(agent_class, "name") or not agent_class.name:
        raise ValueError(f"Agent class {agent_class.__name__} must have a 'name' attribute")

    existing = _AGENT_REGISTRY.get(agent_class.name)
    if existing is not None and existing is not agent_class:
        raise ValueError(
            f"Agent name conflict for '{agent_class.name}': {existing.__name__} already registered, cannot register {agent_class.__name__}"
        )

    _AGENT_REGISTRY[agent_class.name] = agent_class
    return agent_class


def get_agent(name: str) -> BaseAgent:
    """
    Get an agent instance by name.

    Args:
        name: Agent name (e.g., "browser-use", "skyvern")

    Returns:
        An instance of the requested agent

    Raises:
        ValueError: If the agent name is not registered
    """
    if name not in _AGENT_REGISTRY:
        available = ", ".join(sorted(_AGENT_REGISTRY.keys()))
        raise ValueError(f"Unknown agent: '{name}'. Available: {available}")

    return _AGENT_REGISTRY[name]()


def list_agents() -> list[str]:
    """Return a list of all registered agent names."""
    return sorted(_AGENT_REGISTRY.keys())
