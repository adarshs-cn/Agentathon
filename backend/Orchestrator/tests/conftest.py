import os

import pytest

from orchestrator.agents.stubs import default_agents
from orchestrator.context import Context
from orchestrator.simulator.borrowers import SAMPLE_BORROWERS


@pytest.fixture
def ctx():
    """A context with the three stub channel agents registered and 10 sample borrowers."""
    c = Context.create(agents=default_agents())
    c.borrowers.seed(SAMPLE_BORROWERS)
    return c


@pytest.fixture(autouse=True)
def _never_real_channels(monkeypatch):
    """Tests must never use the real email / voice agents, whatever the developer's .env says. Some tests call
    build_advisor(), which loads .env into os.environ, so the switches are removed before EVERY test."""
    for k in [k for k in os.environ if k.startswith("MT02_REAL_")]:
        monkeypatch.delenv(k, raising=False)
