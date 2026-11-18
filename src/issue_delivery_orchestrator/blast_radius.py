from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .config import settings
from .errors import OrchestrationError, RunBlocked
from .github import GitHubClient
from .review import assert_review_converged
from .state import now, run_root, save_state, target_branch
from .util import atomic_write_json, code_head, read_json, run

SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts")
DECLARATION = re.compile(
    r"^(export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(?:const|let|var|function\*?|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)"
)
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)

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
    _assert_reviewed_head(state, worktree)
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
    shared = _shared_impact(worktree, base, head, code, rules)
    for library, impact in shared.items():
        if len(impact["products"]) >= rules["minProducts"]:
            triggers.append({
                "id": "sharedLibrary",
                "label": f"Librería compartida `{library}`",
                "evidence": _impact_text(impact),
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
            "sharedLibraries": shared,
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


def _assert_reviewed_head(state: dict[str, Any], worktree: Path) -> None:
    """Require a quiet review round and a passing gate on the pushed HEAD, lesson commits included.

    Pushing the lesson cards starts a new bot review after the convergence closed; the blast
    radius must not be published before that review is processed.
    """
    local = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    snapshot_path = (state.get("artifacts") or {}).get("latestReviewSnapshot")
    snapshot = read_json(worktree / snapshot_path, {}) if snapshot_path else {}
    if snapshot.get("headSha") != local:
        raise RunBlocked(
            f"The last review round did not run on HEAD {local[:7]}; push it, run wait-review, "
            "triage the new comments and run review-gate before the blast radius"
        )
    if assert_review_converged(state).get("headSha") != local:
        raise RunBlocked("The PR head moved since the last review round; push it and wait again")


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


def _shared_impact(
    worktree: Path, base: str, head: str, code: list[dict[str, Any]], rules: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Find which products use the code changed in each shared library.

    For source files it follows the declarations the diff touches, and every declaration in the
    library that references them, up to the exported names apps import. Other files count the
    whole library as used.
    """
    patterns = [f"{pattern}/*" for pattern in rules["sharedLibraries"]]
    paths: dict[str, list[str]] = {}
    for item in code:
        if _matches(item["path"], patterns):
            paths.setdefault("/".join(item["path"].split("/")[:2]), []).append(item["path"])
    result = {}
    for root, changed in sorted(paths.items()):
        library = root.split("/")[1]
        if all(path.endswith(SOURCE_SUFFIXES) for path in changed):
            touched = set()
            for path in changed:
                touched |= _touched_names(worktree, base, head, path)
            names = _exported_closure(worktree, root, touched, rules)
            consumers = _apps_using(worktree, names, rules)
        else:
            names = []
            consumers = _apps_using(worktree, [f"{rules['importPrefix']}{library}"], rules, fixed=True)
        products: dict[str, list[str]] = {}
        for app in consumers:
            products.setdefault(_product(app, rules), []).append(app)
        result[library] = {"symbols": names, "wholeLibrary": not names and bool(consumers), "products": products}
    return result


def _touched_names(worktree: Path, base: str, head: str, path: str) -> set[str]:
    diff = run(["git", "diff", "-U0", "--no-renames", base, head, "--", path], cwd=worktree).stdout
    old: set[int] = set()
    new: set[int] = set()
    for match in HUNK.finditer(diff):
        start, count = int(match[1]), int(match[2] if match[2] is not None else 1)
        old.update(range(start, start + count))
        start, count = int(match[3]), int(match[4] if match[4] is not None else 1)
        new.update(range(start, start + count))
    names = set()
    for revision, lines in ((base, old), (head, new)):
        text = run(["git", "show", f"{revision}:{path}"], cwd=worktree, check=False).stdout
        for name, _exported, first, last in _declarations(text):
            if any(first <= line <= last for line in lines):
                names.add(name)
    return names


def _declarations(text: str) -> list[tuple[str, bool, int, int]]:
    """Top-level declarations with their line ranges; a range ends where the next one starts."""
    lines = text.splitlines()
    starts = [
        (number, match[2], bool(match[1]))
        for number, line in enumerate(lines, start=1)
        if (match := DECLARATION.match(line))
    ]
    return [
        (name, exported, start, starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines))
        for index, (start, name, exported) in enumerate(starts)
    ]


def _exported_closure(worktree: Path, root: str, touched: set[str], rules: dict[str, Any]) -> list[str]:
    bodies: dict[str, list[str]] = {}
    exported: set[str] = set()
    for path in run(["git", "ls-files", "--", root], cwd=worktree).stdout.splitlines():
        if not path.endswith(SOURCE_SUFFIXES) or _matches(path, rules["testPaths"]):
            continue
        text = (worktree / path).read_text(errors="replace")
        lines = text.splitlines()
        for name, is_exported, first, last in _declarations(text):
            bodies.setdefault(name, []).append("\n".join(lines[first - 1:last]))
            if is_exported:
                exported.add(name)
    affected = set(touched)
    pending = set(touched)
    while pending:
        reference = re.compile(r"\b(?:%s)\b" % "|".join(map(re.escape, sorted(pending))))
        pending = {
            name
            for name, texts in bodies.items()
            if name not in affected and any(reference.search(text) for text in texts)
        }
        affected |= pending
    return sorted(affected & exported)


def _apps_using(worktree: Path, needles: list[str], rules: dict[str, Any], *, fixed: bool = False) -> list[str]:
    apps = set()
    for index in range(0, len(needles), 200):
        chunk = needles[index:index + 200]
        command = ["git", "grep", "-l"]
        command += ["-F", *[part for needle in chunk for part in ("-e", needle)]] if fixed else [
            "-w", "-E", "|".join(re.escape(needle) for needle in chunk)
        ]
        output = run([*command, "--", "apps"], cwd=worktree, check=False).stdout
        apps |= {
            path.split("/")[1]
            for path in output.splitlines()
            if path.count("/") > 1 and not _matches(path, rules["testPaths"])
        }
    return sorted(apps)


def _product(app: str, rules: dict[str, Any]) -> str:
    return next(
        (product for product, apps in rules.get("productGroups", {}).items() if app in apps),
        app,
    )


def _impact_text(impact: dict[str, Any]) -> str:
    products = impact["products"]
    if not products:
        return "lo cambiado no lo usa ninguna app"
    users = ", ".join(f"{product} ({', '.join(apps)})" for product, apps in sorted(products.items()))
    names = impact["symbols"]
    subject = (
        "la librería completa"
        if impact["wholeLibrary"]
        else ", ".join(f"`{name}`" for name in names[:5]) + (f" y {len(names) - 5} más" if len(names) > 5 else "")
    )
    if len(products) == 1:
        return f"{subject} lo usa solo {users}"
    return f"{subject} lo usan {len(products)} productos, {users}"


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
            f"- Librería compartida `{library}`, no sale de un producto: {_impact_text(impact)}"
            for library, impact in signals["sharedLibraries"].items()
            if len(impact["products"]) < rules["minProducts"]
        ),
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
