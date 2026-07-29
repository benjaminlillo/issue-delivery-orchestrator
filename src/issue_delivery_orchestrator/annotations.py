from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .annotation_canvas import AnnotationCanvas
from .annotation_schema import normalize_callouts
from .errors import OrchestrationError
from .png_codec import PngImage, decode_png, encode_png


def annotate_png(source: Path, target: Path, callouts: list[dict[str, Any]]) -> None:
    try:
        image = _decode_screenshot(source)
    except (OSError, ValueError) as error:
        raise OrchestrationError(f"Cannot annotate PNG {source}: {error}") from error
    canvas = AnnotationCanvas(image)
    for label, callout in enumerate(callouts, start=1):
        canvas.callout(callout, label)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode_png(image))


def normalize_png(source: Path, target: Path) -> None:
    try:
        image = _decode_screenshot(source)
    except (OSError, ValueError) as error:
        raise OrchestrationError(f"Cannot normalize screenshot {source}: {error}") from error
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode_png(image))


def validate_screenshot(source: Path) -> None:
    try:
        _decode_screenshot(source)
    except (OSError, ValueError) as error:
        raise OrchestrationError(f"Invalid screenshot {source}: {error}") from error


def is_png(path: Path) -> bool:
    with path.open("rb") as screenshot:
        return screenshot.read(8) == b"\x89PNG\r\n\x1a\n"


def _decode_screenshot(source: Path) -> PngImage:
    payload = source.read_bytes()
    try:
        return decode_png(payload)
    except ValueError:
        if not payload.startswith(b"\xff\xd8\xff"):
            raise
    with tempfile.TemporaryDirectory(prefix="issue-delivery-image-") as raw:
        converted = Path(raw) / "normalized.png"
        commands = _converter_commands(source, converted)
        for command in commands:
            result = subprocess.run(command, text=True, capture_output=True)
            if result.returncode == 0 and converted.is_file():
                return decode_png(converted.read_bytes())
        raise ValueError(
            "JPEG screenshot requires sips, ImageMagick, or ffmpeg for PNG normalization"
        )


def _converter_commands(source: Path, target: Path) -> list[list[str]]:
    candidates = (
        ("/usr/bin/sips", ["-s", "format", "png", str(source), "--out", str(target)]),
        ("magick", [str(source), str(target)]),
        ("convert", [str(source), str(target)]),
        (
            "ffmpeg",
            ["-loglevel", "error", "-y", "-i", str(source), str(target)],
        ),
    )
    return [
        [binary, *arguments]
        for name, arguments in candidates
        if (binary := shutil.which(name) or (name if Path(name).is_file() else None))
    ]
