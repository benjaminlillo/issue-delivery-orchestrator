from __future__ import annotations

from typing import Any, Iterable

from .errors import OrchestrationError
from .state import PHASES, phases_for_state, save_state


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
    delegated = bool(model) or stage == "local-review"
    spawn = {"fork_turns": "none"} if delegated else None
    if model:
        spawn["model"] = model
    return {
        "stage": stage,
        "model": model,
        "modelSource": "explicit" if model else "principal-session",
        "executor": "native-subagent" if delegated else "principal-session",
        "spawnOptions": spawn,
    }
