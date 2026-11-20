"""Two stub agents. No real logic: they 'send' a message and return a result.
Faults are NOT hard-coded here; they are triggered by the FaultInjector."""


class AgentCrash(Exception):
    """Agent process died mid-run."""


class AgentTimeout(Exception):
    """Agent stopped responding (a fault type the supervisor has no script for)."""


class StubAgent:
    def __init__(self, name, injector):
        self.name = name
        self.injector = injector

    def run(self, account_id, attempt, send):
        fault = self.injector.fault_for(self.name, account_id, attempt)

        if fault == "CRASH_BEFORE_SEND":
            raise AgentCrash(f"{self.name} died before contacting {account_id}")
        if fault == "TIMEOUT":
            raise AgentTimeout(f"{self.name} stopped responding on {account_id}")
        if fault == "MALFORMED":
            return {"oops": "not the agreed schema"}
        if fault == "LOOP":
            # alive, but making no progress
            return {"account_id": account_id, "status": "IN_PROGRESS"}

        send(account_id, self.name, f"[{self.name}] message to {account_id}")

        if fault == "CRASH_AFTER_SEND":
            raise AgentCrash(f"{self.name} died AFTER contacting {account_id}")

        return {"account_id": account_id, "status": "DONE", "outcome": "CONTACTED"}


def build_agents(injector):
    return {
        "stub_reminder": StubAgent("stub_reminder", injector),
        "stub_negotiation": StubAgent("stub_negotiation", injector),
    }
