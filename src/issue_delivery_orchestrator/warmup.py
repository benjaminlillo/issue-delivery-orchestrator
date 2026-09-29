from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .errors import RunBlocked
from .state import run_root
from .util import read_json


STATUSES = {"WARMED", "FAILED"}


def validate_warmup(
    state: dict[str, Any],
    raw_path: Any,
    *,
    urls: dict[str, Any],
    runtime_id: str,
    commit: str,
) -> dict[str, Any]:
    """Validate the page warm-up receipt produced against the final runtime.

    A failed page does not block the handoff; it is reported so the user knows which page
    will still compile or fail when opened.
    """
    if not raw_path:
        raise RunBlocked("Runtime handoff input requires 'warmup' with the page warm-up receipt")
    worktree = Path(state["worktree"])
    path = Path(str(raw_path))
    candidate = (path if path.is_absolute() else worktree / path).resolve()
    try:
        candidate.relative_to(run_root(worktree, state["runId"]).resolve())
    except ValueError as error:
        raise RunBlocked("Warm-up receipt must live inside the run directory") from error
    try:
        receipt = read_json(candidate)
    except (OSError, json.JSONDecodeError) as error:
        raise RunBlocked(f"Could not read warm-up receipt: {error}") from error
    if not isinstance(receipt, dict):
        raise RunBlocked("Warm-up receipt must be a JSON object")
    if receipt.get("verifiedCommit") != commit:
        raise RunBlocked(f"Warm-up receipt does not target the handoff commit {commit}")
    if receipt.get("runtimeId") != runtime_id:
        raise RunBlocked(f"Warm-up receipt does not target the final runtime {runtime_id}")
    raw_pages = receipt.get("pages")
    if not isinstance(raw_pages, list):
        raise RunBlocked("Warm-up receipt requires a 'pages' array")
    skip_reason = str(receipt.get("skipReason") or "").strip()
    if not raw_pages and not skip_reason:
        raise RunBlocked("A warm-up receipt without pages requires 'skipReason'")

    pages = []
    for item in raw_pages:
        if not isinstance(item, dict):
            raise RunBlocked("Every warmed page must be an object")
        service = str(item.get("service") or "")
        base = str(urls.get(service) or "").rstrip("/")
        if not base:
            raise RunBlocked(f"Warmed page references unknown runtime service {service or '<empty>'}")
        page_path = str(item.get("path") or "")
        if not page_path.startswith("/"):
            raise RunBlocked(f"Warmed page path for {service} must start with '/'")
        status = str(item.get("status") or "")
        if status not in STATUSES:
            raise RunBlocked("Warmed page status must be WARMED or FAILED")
        http_status = item.get("httpStatus")
        duration = item.get("durationMs")
        if http_status is not None and type(http_status) is not int:
            raise RunBlocked("Warmed page httpStatus must be an integer")
        if duration is not None and (type(duration) is not int or duration < 0):
            raise RunBlocked("Warmed page durationMs must be a non-negative integer")
        error = str(item.get("error") or "").strip()
        if status == "FAILED" and not error:
            raise RunBlocked(f"Failed warm-up of {page_path} requires 'error'")
        pages.append({
            "service": service,
            "url": urljoin(f"{base}/", page_path.lstrip("/")),
            "status": status,
            **({"httpStatus": http_status} if http_status is not None else {}),
            **({"durationMs": duration} if duration is not None else {}),
            **({"error": error} if error else {}),
        })
    return {
        "receipt": str(candidate.relative_to(worktree.resolve())),
        "warmed": sum(page["status"] == "WARMED" for page in pages),
        "failed": sum(page["status"] == "FAILED" for page in pages),
        "pages": pages,
        **({"skipReason": skip_reason} if skip_reason else {}),
    }
