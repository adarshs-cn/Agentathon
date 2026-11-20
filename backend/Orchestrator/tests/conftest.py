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
