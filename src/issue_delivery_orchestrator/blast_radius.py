from __future__ import annotations

import json
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .config import settings
from .errors import OrchestrationError, RunBlocked
from .github import GitHubClient
from .state import now, run_root, save_state, target_branch
from .util import atomic_write_json, code_head, read_json, run

LEVELS = {
    "alto": "pedir review externa",
    "medio": "revisar tú el diff en las señales listadas; review externa opcional",
    "bajo": "merge directo",
}


def assess_blast_radius(state: dict[str, Any], input_path: Path) -> dict[str, Any]:
    """Score the handed-off PR against the profile's blast radius rules and publish it last."""
    if not state.get("pr"):
        raise RunBlocked("There is no PR to assess")
    if state.get("status") != "completed_preserved":
        raise RunBlocked("Assess the blast radius only after the final runtime handoff of a full run")
    worktree = Path(state["worktree"])
    head = code_head(worktree)
    if head != (state.get("finalRuntimeHandoff") or {}).get("verifiedCommit"):
        raise RunBlocked("Code changed since the final handoff; finish the repair flow first")
    rules = _rules()
    payload = read_json(input_path, None)
    judged = _judged_checks(payload, rules["judgedTriggers"])
    notes = [str(note).strip() for note in payload.get("notes") or []]

    target = target_branch(state)
    run(["git", "fetch", "--quiet", "origin", target], cwd=worktree, check=False)
    base = run(["git", "merge-base", f"origin/{target}", head], cwd=worktree).stdout.strip()
    files = _changed_files(worktree, base, head, rules)
    code = [item for item in files if not item["test"]]
    tests = [item for item in files if item["test"]]
    code_lines = sum(item["added"] + item["deleted"] for item in code)
    units = sorted({_unit(item["path"], rules) for item in code} - {None})

    triggers = []
    migrations = [item["path"] for item in files if _matches(item["path"], rules["migrationPaths"])]
    if migrations:
        triggers.append({"id": "migration", "label": "Migración", "evidence": ", ".join(migrations)})
    for library, consumers in _shared_libraries(worktree, code, rules).items():
        if len(consumers) >= rules["minConsumers"]:
            triggers.append({
                "id": "sharedLibrary",
                "label": f"Librería compartida `{library}`",
                "evidence": f"{len(consumers)} apps la usan ({', '.join(consumers)})",
            })
    for key, check in judged.items():
        if check["triggered"]:
            triggers.append(
                {"id": key, "label": rules["judgedTriggers"][key], "evidence": check["evidence"]}
            )

    skips = len((state.get("skipSummary") or {}).get("commentIds") or [])
    reasons = []
    if code_lines > rules["lowRiskMaxChangedLines"]:
        reasons.append(f"{code_lines} líneas de código cambiadas (bajo hasta {rules['lowRiskMaxChangedLines']})")
    if len(units) > rules["lowRiskMaxUnits"]:
        reasons.append(f"toca {len(units)} apps o librerías")
    if code and not tests:
        reasons.append("cambia código sin cambiar tests")
    if skips:
        reasons.append(f"{skips} blockers de bots quedaron como SKIP")
    level = "alto" if triggers else "medio" if reasons else "bajo"

    assessment = {
        "level": level,
        "recommendation": LEVELS[level],
        "triggers": triggers,
        "mediumReasons": reasons,
        "judgedChecks": judged,
        "signals": {
            "files": len(files),
            "codeLinesAdded": sum(item["added"] for item in code),
            "codeLinesDeleted": sum(item["deleted"] for item in code),
            "testFiles": len(tests),
            "units": units,
            "skips": skips,
        },
        "notes": [note for note in notes if note],
        "headSha": head,
        "assessedAt": now(),
    }
    body = _comment(state, assessment, rules)
    github = GitHubClient(worktree)
    github.verify_identity()
    assessment["commentReference"] = github.repost_comment(state["pr"]["number"], _marker(state), body)
    path = run_root(worktree, state["runId"]) / "review" / "blast-radius.json"
    atomic_write_json(path, assessment)
    state["blastRadius"] = {
        key: assessment[key] for key in ("level", "recommendation", "headSha", "assessedAt", "commentReference")
    }
    state.setdefault("artifacts", {})["blastRadius"] = str(path.relative_to(worktree))
    save_state(state)
    return {**assessment, "markdown": body}


def _rules() -> dict[str, Any]:
    profile = json.loads(settings().profile_path.read_text())
    rules = profile.get("blastRadius")
    if not isinstance(rules, dict):
        raise OrchestrationError("The profile has no blastRadius rules")
    return rules


def _judged_checks(payload: Any, triggers: dict[str, str]) -> dict[str, dict[str, Any]]:
    checks = (payload or {}).get("checks") if isinstance(payload, dict) else None
    if not isinstance(checks, dict):
        raise RunBlocked("The input needs a checks object with one entry per judged trigger")
    missing = [key for key in triggers if key not in checks]
    unknown = [key for key in checks if key not in triggers]
    if missing or unknown:
        raise RunBlocked(f"Judge exactly these triggers: {list(triggers)}; missing={missing} unknown={unknown}")
    result = {}
    for key in triggers:
        check = checks[key] if isinstance(checks[key], dict) else {}
        evidence = str(check.get("evidence") or "").strip()
        if not isinstance(check.get("triggered"), bool) or not evidence:
            raise RunBlocked(f"Check {key} needs a boolean triggered and its evidence")
        result[key] = {"triggered": check["triggered"], "evidence": evidence}
    return result


def _changed_files(worktree: Path, base: str, head: str, rules: dict[str, Any]) -> list[dict[str, Any]]:
    output = run(["git", "diff", "--numstat", "--no-renames", base, head], cwd=worktree).stdout
    files = []
    for line in output.splitlines():
        added, deleted, path = line.split("\t", 2)
        if _matches(path, rules["ignoredPaths"]):
            continue
        files.append({
            "path": path,
            "added": int(added) if added.isdigit() else 0,
            "deleted": int(deleted) if deleted.isdigit() else 0,
            "test": _matches(path, rules["testPaths"]),
        })
    return files


def _unit(path: str, rules: dict[str, Any]) -> str | None:
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 and parts[0] in rules["unitRoots"] else None


def _shared_libraries(worktree: Path, code: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, list[str]]:
    libraries = sorted({
        path.split("/")[1]
        for path in (item["path"] for item in code)
        if _matches(path, [f"{pattern}/*" for pattern in rules["sharedLibraries"]])
    })
    result = {}
    for library in libraries:
        output = run(
            ["git", "grep", "-l", "-F", f"{rules['importPrefix']}{library}", "--", "apps"],
            cwd=worktree,
            check=False,
        ).stdout
        result[library] = sorted({path.split("/")[1] for path in output.splitlines() if "/" in path})
    return result


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def _marker(state: dict[str, Any]) -> str:
    return f"<!-- issue-delivery-blast-radius:{state['runId']} -->"


def _comment(state: dict[str, Any], assessment: dict[str, Any], rules: dict[str, Any]) -> str:
    signals = assessment["signals"]
    lines = [
        _marker(state),
        f"## Blast radius: {assessment['level']}",
        "",
        f"Recomendación: {assessment['recommendation']}.",
        "",
    ]
    if assessment["triggers"]:
        lines += ["Disparadores:", *(f"- {item['label']}: {item['evidence']}" for item in assessment["triggers"]), ""]
    if assessment["mediumReasons"]:
        lines += ["Otras señales de riesgo:", *(f"- {reason}" for reason in assessment["mediumReasons"]), ""]
    lines += [
        "Medición:",
        f"- {signals['files']} archivos cambiados, {signals['testFiles']} de tests",
        f"- Código: +{signals['codeLinesAdded']}/-{signals['codeLinesDeleted']} líneas",
        f"- Apps y librerías: {', '.join(signals['units']) or 'ninguna'}",
        f"- SKIPs publicados: {signals['skips']}",
        *(
            f"- {label}, no aplica: {assessment['judgedChecks'][key]['evidence']}"
            for key, label in rules["judgedTriggers"].items()
            if not assessment["judgedChecks"][key]["triggered"]
        ),
        "",
    ]
    if assessment["notes"]:
        lines += ["Notas:", *(f"- {note}" for note in assessment["notes"]), ""]
    lines.append(f"Calculado sobre `{assessment['headSha'][:7]}`.")
    return "\n".join(lines)
