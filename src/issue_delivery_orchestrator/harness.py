from __future__ import annotations

import os

from .errors import RunBlocked


def detect_host() -> tuple[str | None, str | None]:
    """Return the agent host and its session ID from the environment it exports to commands."""
    codex = os.environ.get("CODEX_THREAD_ID", "").strip()
    claude = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    in_claude = bool(claude) or os.environ.get("CLAUDECODE") == "1"
    if codex and in_claude:
        return "ambiguous", None
    if in_claude:
        return "claude", claude or None
    if codex:
        return "codex", codex
    return None, None


def current_harness() -> str:
    """Identify the host for native subagents; Codex remains the default when none is detected."""
    host, _ = detect_host()
    if host == "ambiguous":
        raise RunBlocked(
            "Ambiguous agent host: both Codex and Claude Code session variables are set"
        )
    return host or "codex"


def native_reviewer() -> str:
    return f"{current_harness()}-native-subagent"
