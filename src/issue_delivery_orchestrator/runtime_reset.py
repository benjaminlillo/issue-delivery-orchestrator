from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import RunBlocked
from .runtime import cleanup_runtimes, initialize_runtime, stop_owned_processes
from .state import handoff_mode, now, run_root, save_state
from .util import atomic_write_json, run


def reset_final_runtime(state: dict[str, Any]) -> dict[str, Any]:
    _require_final_boundary(state)
    worktree = Path(state["worktree"])
    dirty = run(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=worktree
    ).stdout.strip()
    if dirty:
        raise RunBlocked(
            "Final runtime reset requires a clean committed worktree; "
            "commit or remove pending product changes first"
        )
    commit = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    previous_runtime_id = state.get("activeRuntimeId")
    stopped = stop_owned_processes(state)
    cleaned = cleanup_runtimes(state)
    runtime = initialize_runtime(state, fresh=True)
    receipt = {
        "receiptVersion": 1,
        "status": "READY_TO_START_SERVICES",
        "verifiedCommit": commit,
        "previousRuntimeId": previous_runtime_id,
        "runtimeId": runtime["runtimeId"],
        "stoppedPids": stopped,
        "cleanedRuntimeIds": cleaned,
        "resetAt": now(),
    }
    receipt_path = run_root(worktree, state["runId"]) / "validation" / "final-runtime-reset.json"
    atomic_write_json(receipt_path, receipt)
    state["finalRuntimeReset"] = {
        **receipt,
        "receipt": str(receipt_path.relative_to(worktree)),
    }
    previous_handoff = state.get("finalRuntimeHandoff")
    if isinstance(previous_handoff, dict):
        previous_handoff["status"] = "superseded"
        previous_handoff["supersededAt"] = now()
    state["status"] = "preparing_final_runtime"
    state["blocker"] = None
    save_state(state)
    return {
        "reset": receipt,
        "receiptPath": str(receipt_path),
        "nextAction": "Start the required apps on the active runtime, then publish runtime-handoff",
    }


def _require_final_boundary(state: dict[str, Any]) -> None:
    if handoff_mode(state) == "manual-runtime":
        valid = (
            state.get("currentPhase") == "manual-revision"
            and state.get("status") in {"active", "preparing_final_runtime"}
        )
    else:
        valid = (
            state.get("currentPhase") is None
            and state.get("status")
            in {"awaiting_final_runtime_reset", "preparing_final_runtime"}
        )
    if not valid:
        raise RunBlocked(
            "Final runtime reset is available only at the configured delivery boundary"
        )
