from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import settings
from .errors import RunBlocked
from .state import now, run_root, save_state
from .util import read_json, run


RESTORABLE_STATUSES = {"awaiting_manual_review", "completed_preserved"}


def restore_runtime(state: dict[str, Any]) -> dict[str, Any]:
    """Restart the handed-off runtime after its processes stopped, without changing code.

    Conductor Cloud stops every process when an idle workspace sleeps. This restarts the
    shared infrastructure and the same registered services on the same runtime and ports,
    then returns the run to the final handoff so warm-up and `runtime-handoff` run again.
    """
    if state.get("status") not in RESTORABLE_STATUSES:
        raise RunBlocked("Only a handed-off runtime can be restored; finish the final handoff first")
    handoff = state.get("finalRuntimeHandoff") or {}
    runtime_id = handoff.get("runtimeId")
    if handoff.get("status") != "ready" or runtime_id != state.get("activeRuntimeId"):
        raise RunBlocked("The final runtime handoff does not match the active runtime")
    worktree = Path(state["worktree"])
    dirty = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=worktree).stdout.strip()
    head = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if dirty or head != handoff.get("verifiedCommit"):
        raise RunBlocked("Code changed since the handoff; use resume and repeat the repair flow instead")
    configuration = settings()
    if not configuration.runtime_services_command:
        raise RunBlocked("The profile does not configure runtime.servicesCommand")
    services = [str(item["name"]) for item in handoff.get("services", [])]
    if not services:
        raise RunBlocked("The final runtime handoff records no services to restore")

    commands = []
    if os.environ.get("CONDUCTOR_IS_LOCAL") == "0" and configuration.runtime_cloud_services_command:
        commands.append(list(configuration.runtime_cloud_services_command))
    # Without --replace, the init command reuses the runtime bound to this worktree.
    commands.append(list(configuration.runtime_init_command))
    commands.append(_expand(configuration.runtime_services_command, services))

    log_path = run_root(worktree, state["runId"]) / "logs" / "runtime-restore.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        for command in commands:
            result = run(command, cwd=worktree, check=False)
            log.write(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}\n")
            if result.returncode != 0:
                raise RunBlocked(
                    f"Runtime restore failed at `{' '.join(command)}`; see {log_path.relative_to(worktree)}"
                )
    binding = read_json(worktree / configuration.runtime_root / "worktree.json", {})
    if binding.get("runtimeId") != runtime_id:
        raise RunBlocked("Runtime restore bound a different runtime; reset the final runtime instead")

    state["status"] = "preparing_final_runtime"
    state["runtimeRestore"] = {
        "restoredAt": now(),
        "runtimeId": runtime_id,
        "services": services,
        "log": str(log_path.relative_to(worktree)),
    }
    save_state(state)
    return {
        "runtimeId": runtime_id,
        "services": services,
        "log": state["runtimeRestore"]["log"],
        "next": "Warm up the pages again and run runtime-handoff with the same services",
    }


def _expand(template: tuple[str, ...], services: list[str]) -> list[str]:
    command: list[str] = []
    for part in template:
        command.extend(services if part == "{services}" else [part])
    return command
