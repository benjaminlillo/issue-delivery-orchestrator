from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .errors import OrchestrationError
from .github import GitHubClient
from .linear import LinearClient
from .state import review_method, run_root, save_state
from .util import atomic_write_json, ensure_within, read_json, run


def publish_evidence(
    state: dict[str, Any],
    manifest_path: Path,
    *,
    linear: LinearClient,
    github: GitHubClient | None,
) -> dict[str, Any]:
    worktree = Path(state["worktree"])
    manifest_path = ensure_within(manifest_path, worktree)
    manifest = read_json(manifest_path)
    verification = _verification(manifest, state, worktree)
    screenshots = _screenshots(manifest, worktree)
    if not screenshots:
        raise OrchestrationError("Evidence manifest contains no screenshots")

    root = run_root(worktree, state["runId"])
    receipt_path = root / "evidence" / "publication-receipt.json"
    fingerprint = _fingerprint(screenshots, verification)
    previous = read_json(receipt_path, {})
    if previous.get("fingerprint") == fingerprint:
        assets = previous["assets"]
        newly_uploaded = False
    else:
        assets = [
            {
                **item,
                "path": str(item["path"].relative_to(worktree)),
                "url": linear.upload_file(item["path"]),
            }
            for item in screenshots
        ]
        newly_uploaded = True
        atomic_write_json(
            receipt_path,
            {
                "fingerprint": fingerprint,
                "assets": assets,
                "verification": verification,
                "status": "uploaded",
                "linearIssue": None,
                "prCommentId": None,
            },
        )

    pr = state.get("pr")
    if pr and github:
        assets = _ensure_github_assets(state, assets, screenshots, github)

    issue = linear.issue(state["issue"]["identifier"])
    section = _linear_run_section(state["runId"], assets)
    description = upsert_ui_run(issue.description, state["runId"], section)
    linear.update_description(issue.id, description)
    if newly_uploaded:
        linear.post_comment(
            issue.id,
            f"Evidencia UI final actualizada para la ejecución `{state['runId']}`.",
        )

    pr_comment_id = None
    if pr and github:
        marker = f"<!-- issue-delivery-ui-evidence:{state['runId']} -->"
        pr_body = _pr_body(
            marker,
            assets,
            provider=verification.get("provider", "cua-driver"),
        )
        pr_comment_id = github.upsert_comment(int(pr["number"]), marker, pr_body)

    receipt = {
        "fingerprint": fingerprint,
        "assets": assets,
        "verification": verification,
        "status": "published",
        "linearIssue": issue.url,
        "prCommentId": pr_comment_id,
    }
    atomic_write_json(receipt_path, receipt)
    state["artifacts"]["uiEvidenceReceipt"] = str(receipt_path.relative_to(worktree))
    save_state(state)
    return receipt


def repair_github_evidence(
    state: dict[str, Any],
    *,
    github: GitHubClient,
) -> dict[str, Any]:
    worktree = Path(state["worktree"])
    root = run_root(worktree, state["runId"])
    receipt_path = root / "evidence" / "publication-receipt.json"
    receipt = read_json(receipt_path)
    if not isinstance(receipt, dict) or not isinstance(receipt.get("assets"), list):
        raise OrchestrationError(f"Published evidence receipt not found: {receipt_path}")
    if not state.get("pr"):
        raise OrchestrationError("Cannot repair GitHub evidence without a recorded PR")
    screenshots = []
    for index, asset in enumerate(receipt["assets"], start=1):
        path = ensure_within(worktree / str(asset.get("path") or ""), worktree)
        if not path.is_file() or path.suffix.lower() != ".png":
            raise OrchestrationError(f"Evidence asset {index} is unavailable: {path}")
        screenshots.append({**asset, "path": path})
    assets = _ensure_github_assets(
        state,
        receipt["assets"],
        screenshots,
        github,
        force=not all(asset.get("githubUrl") for asset in receipt["assets"]),
    )
    marker = f"<!-- issue-delivery-ui-evidence:{state['runId']} -->"
    comment_id = github.upsert_comment(
        int(state["pr"]["number"]),
        marker,
        _pr_body(
            marker,
            assets,
            provider=(receipt.get("verification") or {}).get(
                "provider",
                "cua-driver",
            ),
        ),
    )
    updated = {
        **receipt,
        "assets": assets,
        "githubEvidenceBranch": github.evidence_branch,
        "prCommentId": comment_id,
        "status": "published",
    }
    atomic_write_json(receipt_path, updated)
    return updated


def upsert_ui_run(description: str, run_id: str, run_section: str) -> str:
    section_name = settings().linear_ui_section
    heading = re.search(rf"(?im)^## {re.escape(section_name)}\s*$", description)
    if not heading:
        return f"{description.rstrip()}\n\n## {section_name}\n\n{run_section.rstrip()}\n"
    following = re.search(
        rf"(?m)^## (?!{re.escape(section_name)}\s*$).+$",
        description[heading.end() :],
    )
    end = heading.end() + (following.start() if following else len(description[heading.end() :]))
    body = description[heading.end() : end]
    run_pattern = re.compile(
        rf"(?ms)^### Issue Delivery {re.escape(run_id)}\s*$.*?(?=^### |\Z)"
    )
    if run_pattern.search(body):
        updated = run_pattern.sub(run_section.rstrip() + "\n", body)
    else:
        updated = body.rstrip() + "\n\n" + run_section.rstrip() + "\n"
    return description[: heading.end()] + updated + description[end:]


def _screenshots(manifest: Any, worktree: Path) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("screenshots"), list):
        raise OrchestrationError("Evidence manifest must contain a screenshots array")
    result = []
    for index, item in enumerate(manifest["screenshots"], start=1):
        if not isinstance(item, dict):
            raise OrchestrationError(f"Screenshot {index} must be an object")
        path = ensure_within(worktree / str(item.get("path") or ""), worktree)
        if not path.is_file() or path.suffix.lower() != ".png":
            raise OrchestrationError(f"Screenshot {index} is not a PNG file: {path}")
        story_id = str(item.get("storyId") or "").strip()
        title = str(item.get("title") or path.stem).strip()
        if not story_id:
            raise OrchestrationError(f"Screenshot {index} is missing storyId")
        result.append(
            {
                "storyId": story_id,
                "title": title,
                "caption": str(item.get("caption") or "").strip(),
                "path": path,
            }
        )
    return result


def _fingerprint(
    screenshots: list[dict[str, Any]],
    verification: dict[str, Any],
) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(verification, sort_keys=True).encode())
    for item in screenshots:
        digest.update(item["storyId"].encode())
        digest.update(item["title"].encode())
        digest.update(item["caption"].encode())
        digest.update(item["path"].read_bytes())
    return digest.hexdigest()


def _ensure_github_assets(
    state: dict[str, Any],
    assets: list[dict[str, Any]],
    screenshots: list[dict[str, Any]],
    github: GitHubClient,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    if not force and assets and all(asset.get("githubUrl") for asset in assets):
        return assets
    files: list[tuple[Path, str]] = []
    targets: list[str] = []
    for index, screenshot in enumerate(screenshots, start=1):
        target = _evidence_target_path(state, screenshot, index)
        files.append((screenshot["path"], target))
        targets.append(target)
    urls = github.publish_evidence_files(
        files,
        message=f"chore(evidence): publish UI evidence for {state['issue']['identifier']}",
    )
    return [
        {
            **asset,
            "githubPath": target,
            "githubUrl": urls[target],
        }
        for asset, target in zip(assets, targets)
    ]


def _evidence_target_path(
    state: dict[str, Any],
    screenshot: dict[str, Any],
    index: int,
) -> str:
    digest = hashlib.sha256(screenshot["path"].read_bytes()).hexdigest()[:12]
    story = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "-",
        str(screenshot.get("storyId") or f"image-{index}"),
    ).strip("-")
    return (
        f".issue-delivery-evidence/{state['issue']['identifier']}/"
        f"{state['runId']}/{index:02d}-{story}-{digest}.png"
    )


def _verification(
    manifest: Any,
    state: dict[str, Any],
    worktree: Path,
) -> dict[str, Any]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("verification"), dict):
        raise OrchestrationError("Evidence manifest is missing the UI verification receipt")
    verification = manifest["verification"]
    if verification.get("status") != "PASS":
        raise OrchestrationError("Evidence publication requires UI verification status PASS")
    selected_provider = review_method(state)
    declared_provider = str(verification.get("provider") or "").strip()
    if declared_provider and declared_provider not in {"cua-driver", "codex-browser"}:
        raise OrchestrationError(
            f"Evidence verification has unsupported provider {declared_provider}"
        )
    if declared_provider and declared_provider != selected_provider:
        raise OrchestrationError(
            f"Evidence provider mismatch: run uses {selected_provider}, "
            f"manifest uses {declared_provider}"
        )
    if not declared_provider and selected_provider != "cua-driver":
        raise OrchestrationError(
            "codex-browser evidence must declare provider 'codex-browser'"
        )
    verified_commit = str(verification.get("verifiedCommit") or "").strip()
    head = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if verified_commit != head:
        raise OrchestrationError(
            f"UI verification is stale: verified {verified_commit or '<empty>'}, current HEAD is {head}"
        )
    runtime_id = str(verification.get("runtimeId") or "").strip()
    registered = {item["runtimeId"] for item in state.get("runtimes", [])}
    if runtime_id not in registered:
        raise OrchestrationError(
            f"UI verification references unregistered runtime {runtime_id or '<empty>'}"
        )
    verified_at = str(verification.get("verifiedAt") or "").strip()
    try:
        datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise OrchestrationError(
            "UI verification verifiedAt must be an ISO-8601 timestamp"
        ) from error
    scenario_ids = verification.get("scenarioIds")
    if not isinstance(scenario_ids, list) or not any(str(item).strip() for item in scenario_ids):
        raise OrchestrationError("UI verification must identify at least one scenario")
    receipt = {
        "status": "PASS",
        "verifiedCommit": verified_commit,
        "runtimeId": runtime_id,
        "verifiedAt": verified_at,
        "scenarioIds": [str(item).strip() for item in scenario_ids if str(item).strip()],
    }
    if declared_provider or state.get("reviewer"):
        receipt["provider"] = declared_provider or selected_provider
    return receipt


def _linear_run_section(run_id: str, assets: list[dict[str, Any]]) -> str:
    items = []
    for asset in assets:
        caption = f"\n\n{asset['caption']}" if asset.get("caption") else ""
        items.append(
            f"#### {asset['storyId']} — {asset['title']}\n\n"
            f"![{asset['title']}]({asset['url']}){caption}"
        )
    return f"### Issue Delivery {run_id}\n\n" + "\n\n".join(items)


def _pr_body(
    marker: str,
    assets: list[dict[str, Any]],
    *,
    provider: str = "cua-driver",
) -> str:
    items = []
    for asset in assets:
        github_url = str(asset.get("githubUrl") or "").strip()
        if not github_url:
            raise OrchestrationError(
                f"GitHub evidence URL missing for {asset.get('storyId') or asset.get('title')}"
            )
        caption = f"\n\n{asset['caption']}" if asset.get("caption") else ""
        items.append(
            f"### {asset['storyId']} — {asset['title']}\n\n"
            f"![{asset['title']}]({github_url}){caption}"
        )
    method = (
        "Browser integrado de Codex"
        if provider == "codex-browser"
        else "Cua Driver"
    )
    return (
        f"{marker}\n"
        "## Evidencia visual final\n\n"
        f"Capturas verificadas mediante {method} sobre el estado aceptado.\n\n"
        + "\n\n".join(items)
    )
