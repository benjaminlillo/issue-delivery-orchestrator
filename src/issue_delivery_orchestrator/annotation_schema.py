from __future__ import annotations

from typing import Any

from .errors import OrchestrationError


def normalize_callouts(value: Any, screenshot_index: int) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise OrchestrationError(
            f"Screenshot {screenshot_index} callouts must contain between one and three items"
        )
    result = []
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise OrchestrationError(
                f"Screenshot {screenshot_index} callout {index} must be an object"
            )
        kind = str(raw.get("kind") or "").strip()
        if kind not in {"highlight", "circle", "arrow"}:
            raise OrchestrationError(
                f"Screenshot {screenshot_index} callout {index} has unsupported kind {kind}"
            )
        caption = str(raw.get("caption") or "").strip()
        if not caption:
            raise OrchestrationError(
                f"Screenshot {screenshot_index} callout {index} is missing caption"
            )
        bounds = _normalized_bounds(raw.get("bounds"), screenshot_index, index)
        callout = {"kind": kind, "caption": caption, "bounds": bounds}
        if kind == "arrow":
            callout["anchor"] = _normalized_point(
                raw.get("anchor"), screenshot_index, index
            )
        elif raw.get("anchor") is not None:
            raise OrchestrationError(
                f"Screenshot {screenshot_index} callout {index} "
                "uses anchor without an arrow"
            )
        result.append(callout)
    return result


def _normalized_bounds(value: Any, screenshot: int, callout: int) -> dict[str, float]:
    if not isinstance(value, dict):
        raise OrchestrationError(
            f"Screenshot {screenshot} callout {callout} is missing bounds"
        )
    result = {
        key: _number(value.get(key), screenshot, callout, key)
        for key in ("x", "y", "width", "height")
    }
    outside = (
        result["width"] <= 0
        or result["height"] <= 0
        or result["x"] + result["width"] > 1
        or result["y"] + result["height"] > 1
    )
    if outside:
        raise OrchestrationError(
            f"Screenshot {screenshot} callout {callout} bounds must fit "
            "within normalized image coordinates"
        )
    if result["width"] * result["height"] > 0.6:
        raise OrchestrationError(
            f"Screenshot {screenshot} callout {callout} covers too much of the image; "
            "use annotationReason for a global change"
        )
    return result


def _normalized_point(value: Any, screenshot: int, callout: int) -> dict[str, float]:
    if not isinstance(value, dict):
        raise OrchestrationError(
            f"Screenshot {screenshot} arrow callout {callout} is missing anchor"
        )
    return {
        key: _number(value.get(key), screenshot, callout, key)
        for key in ("x", "y")
    }


def _number(value: Any, screenshot: int, callout: int, key: str) -> float:
    invalid = (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= float(value) <= 1
    )
    if invalid:
        raise OrchestrationError(
            f"Screenshot {screenshot} callout {callout} {key} "
            "must be between 0 and 1"
        )
    return float(value)
