class OrchestrationError(RuntimeError):
    """A safe, actionable orchestration failure."""


class IdentityMismatch(OrchestrationError):
    """The active credential does not belong to the approved user."""


class RunBlocked(OrchestrationError):
    """The run requires an explicit user decision or external action."""
