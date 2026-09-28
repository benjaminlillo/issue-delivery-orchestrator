from __future__ import annotations

import os


def current_harness() -> str:
    """Identify the agent host running the orchestrator; Codex remains the default."""
    return "claude" if os.environ.get("CLAUDECODE") == "1" else "codex"


def native_reviewer() -> str:
    return f"{current_harness()}-native-subagent"
