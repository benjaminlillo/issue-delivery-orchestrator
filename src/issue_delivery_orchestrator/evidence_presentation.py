from __future__ import annotations

from typing import Any

from .errors import OrchestrationError


def linear_run_section(run_id: str, assets: list[dict[str, Any]]) -> str:
    items = []
    for asset in assets:
        caption = _asset_caption(asset, original_url=asset.get("originalUrl"))
        items.append(
            f"#### {asset['storyId']} — {asset['title']}\n\n"
            f"![{asset['title']}]({asset['url']}){caption}"
        )
    return f"### Issue Delivery {run_id}\n\n" + "\n\n".join(items)


def pr_body(
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
                f"GitHub evidence URL missing for "
                f"{asset.get('storyId') or asset.get('title')}"
            )
        caption = _asset_caption(
            asset,
            original_url=asset.get("githubOriginalUrl"),
        )
        items.append(
            f"### {asset['storyId']} — {asset['title']}\n\n"
            f"![{asset['title']}]({github_url}){caption}"
        )
    method = (
        "Browser integrado de Codex"
        if provider == "codex-browser"
        else "Cua Driver"
    )
    annotation_notice = (
        " Los indicadores numerados son anotaciones de evidencia y no forman "
        "parte de la aplicación."
        if any(asset.get("callouts") for asset in assets)
        else ""
    )
    return (
        f"{marker}\n"
        "## Evidencia visual final\n\n"
        f"Capturas verificadas mediante {method} sobre el estado aceptado."
        f"{annotation_notice}\n\n"
        + "\n\n".join(items)
    )


def _asset_caption(asset: dict[str, Any], *, original_url: str | None) -> str:
    parts = []
    if asset.get("caption"):
        parts.append(str(asset["caption"]))
    callouts = asset.get("callouts") or []
    if callouts:
        parts.extend(
            f"{index}. {callout['caption']}"
            for index, callout in enumerate(callouts, start=1)
        )
        if original_url:
            parts.append(f"[Ver captura original sin anotaciones]({original_url})")
    elif asset.get("annotationReason"):
        parts.append(f"Sin indicador localizado: {asset['annotationReason']}")
    return "\n\n" + "\n\n".join(parts) if parts else ""
