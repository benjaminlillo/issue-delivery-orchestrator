from __future__ import annotations

from typing import Any, Iterable

from .errors import OrchestrationError, RunBlocked
from .harness import current_harness
from .state import PHASES, phases_for_state, review_method, save_state


# Claude Code's Agent tool accepts only these model aliases.
CLAUDE_SUBAGENT_MODELS = ("sonnet", "opus", "haiku", "fable")
# Stages that always run in a fresh worker, and the context package each one receives.
# Long stages would otherwise re-read the principal's accumulated history on every call.
ISOLATED_STAGES = {
    "implement": "ticket",
    "local-review": "independent-review",
    "manual-revision": "black-box-ui",
}
# In-app reviewers (Codex Browser) may be unavailable to workers; keep them in the principal.
WORKER_REVIEWERS = {"playwright-chrome", "cua-driver"}


def _context_package(state: dict[str, Any], stage: str) -> str | None:
    if stage == "manual-revision" and review_method(state) not in WORKER_REVIEWERS:
        return None
    return ISOLATED_STAGES.get(stage)


def parse_stage_models(entries: Iterable[str]) -> dict[str, str]:
    models: dict[str, str] = {}
    for entry in entries:
        stage, separator, model = entry.partition("=")
        stage, model = stage.strip(), model.strip()
        if not separator or stage not in PHASES:
            raise OrchestrationError("Stage model must be STAGE=MODEL with a known phase")
        if not model or any(character.isspace() for character in model):
            raise OrchestrationError("Stage model must be a non-empty model ID or inherit")
        if stage in models and models[stage] != model:
            raise OrchestrationError(f"Conflicting model selections for {stage}")
        models[stage] = model
    return models


def update_stage_models(state: dict[str, Any], selections: dict[str, str]) -> None:
    unknown = set(selections) - set(phases_for_state(state))
    if unknown:
        raise OrchestrationError(f"Stages unavailable in this run: {', '.join(sorted(unknown))}")
    if current_harness() == "claude":
        invalid = sorted(
            f"{stage}={model}" for stage, model in selections.items()
            if model != "inherit" and model not in CLAUDE_SUBAGENT_MODELS
        )
        if invalid:
            raise OrchestrationError(
                f"Claude Code subagents accept only {', '.join(CLAUDE_SUBAGENT_MODELS)}: {', '.join(invalid)}"
            )
    models = dict(state.get("stageModels") or {})
    for stage, model in selections.items():
        if model == "inherit":
            models.pop(stage, None)
        else:
            models[stage] = model
    state["stageModels"] = models
    save_state(state)


def stage_plan(state: dict[str, Any], stage: str) -> dict[str, Any]:
    if stage not in phases_for_state(state):
        raise OrchestrationError(f"Stage unavailable in this run: {stage}")
    model = (state.get("stageModels") or {}).get(stage)
    package = _context_package(state, stage)
    delegated = bool(model) or package is not None
    try:
        harness = current_harness()
    except RunBlocked as error:
        # Keep status readable; the principal must not delegate until the host is unambiguous.
        return {
            "stage": stage, "harness": "ambiguous", "model": model,
            "modelSource": "explicit" if model else "principal-session",
            "executor": "native-subagent" if delegated else "principal-session",
            "spawnOptions": None, "contextPackage": package, "blocked": str(error),
        }
    spawn = None
    if delegated:
        # Both shapes start the worker without the principal's conversation history.
        spawn = {"subagent_type": "general-purpose"} if harness == "claude" else {"fork_turns": "none"}
        if model:
            spawn["model"] = model
    return {
        "stage": stage,
        "harness": harness,
        "model": model,
        "modelSource": "explicit" if model else "principal-session",
        "executor": "native-subagent" if delegated else "principal-session",
        "spawnOptions": spawn,
        "contextPackage": package or ("stage" if delegated else None),
    }
