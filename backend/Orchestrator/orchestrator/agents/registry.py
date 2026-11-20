"""AgentRegistry: the supervisor's directory of channel agents, looked up by name."""
from __future__ import annotations

from orchestrator.agents.base import ChannelAgent


class AgentRegistry:
    def __init__(self, agents: list[ChannelAgent] | tuple = ()):
        self._agents: dict[str, ChannelAgent] = {}
        for a in agents:
            self.register(a)

    def register(self, agent: ChannelAgent) -> None:
        if not agent.name:
            raise ValueError("agent needs a name")
        self._agents[agent.name] = agent

    def get(self, name: str) -> ChannelAgent:
        return self._agents[name]

    def names(self) -> list[str]:
        return list(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents
