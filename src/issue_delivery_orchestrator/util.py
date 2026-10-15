from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .errors import OrchestrationError


def run(
    args: Iterable[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [str(value) for value in args]
    result = subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise OrchestrationError(f"{' '.join(command)} failed: {detail}")
    return result


def read_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return fallback


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def ensure_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise OrchestrationError(f"Artifact must live inside the worktree: {path}") from error
    return resolved


LESSONS_DIRECTORY = "docs/lessons/"


def code_head(worktree: Path) -> str:
    """Return HEAD, skipping trailing commits that only add lesson cards.

    The repository's lessons-learned skill commits cards on the PR branch after the handoff; those
    commits do not change the code that was verified and handed off.
    """
    commit = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    while True:
        parents = run(["git", "rev-list", "--parents", "-n", "1", commit], cwd=worktree).stdout.split()
        if len(parents) != 2:
            return commit
        paths = run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit], cwd=worktree
        ).stdout.split()
        if not paths or not all(path.startswith(LESSONS_DIRECTORY) for path in paths):
            return commit
        commit = parents[1]
