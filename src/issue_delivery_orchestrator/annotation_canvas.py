from __future__ import annotations

from typing import Any

from .png_codec import PngImage
from .raster_canvas import RasterCanvas


YELLOW = (255, 193, 7, 255)
BLACK = (20, 20, 20, 255)
WHITE = (255, 255, 255, 255)
FILL = (255, 193, 7, 52)
DIGITS = {
    "1": ("010", "110", "010", "010", "010", "010", "111"),
    "2": ("110", "001", "001", "010", "100", "100", "111"),
    "3": ("110", "001", "001", "110", "001", "001", "110"),
}


class AnnotationCanvas(RasterCanvas):
    def __init__(self, image: PngImage):
        super().__init__(image)
        shortest = min(image.width, image.height)
        self.inner = max(2, round(shortest / 300))
        self.outer = self.inner + 3
        self.badge = max(11, round(shortest / 48))

    def callout(self, item: dict[str, Any], label: int) -> None:
        bounds = self._bounds(item["bounds"])
        left, top, right, bottom = bounds
        if item["kind"] == "highlight":
            self.fill_rect(bounds, FILL)
            self.rect(bounds, BLACK, self.outer)
            self.rect(bounds, YELLOW, self.inner)
            badge_at = (left, top)
        elif item["kind"] == "circle":
            self.fill_ellipse(bounds, FILL)
            self.ellipse(bounds, BLACK, self.outer)
            self.ellipse(bounds, YELLOW, self.inner)
            badge_at = (left, top)
        else:
            start = self._point(item["anchor"])
            end = ((left + right) // 2, (top + bottom) // 2)
            self.arrow(start, end, BLACK, self.outer + 1, self.badge * 1.2)
            self.arrow(start, end, YELLOW, self.inner, self.badge * 1.2)
            badge_at = start
        self._badge(*badge_at, str(label))

    def _badge(self, x: int, y: int, label: str) -> None:
        self.disc(x, y, self.badge + 2, YELLOW)
        self.disc(x, y, self.badge - 2, BLACK)
        pattern = DIGITS[label]
        scale = max(2, self.badge // 5)
        left, top = x - (3 * scale) // 2, y - (7 * scale) // 2
        for row, bits in enumerate(pattern):
            for column, bit in enumerate(bits):
                if bit == "1":
                    self.fill_rect(
                        (
                            left + column * scale,
                            top + row * scale,
                            left + (column + 1) * scale - 1,
                            top + (row + 1) * scale - 1,
                        ),
                        WHITE,
                    )

    def _bounds(self, value: dict[str, float]) -> tuple[int, int, int, int]:
        left, top = self._point({"x": value["x"], "y": value["y"]})
        right = round((value["x"] + value["width"]) * self.image.width)
        bottom = round((value["y"] + value["height"]) * self.image.height)
        return (
            left,
            top,
            max(left + 1, min(self.image.width - 1, right)),
            max(top + 1, min(self.image.height - 1, bottom)),
        )

    def _point(self, value: dict[str, float]) -> tuple[int, int]:
        return (
            min(self.image.width - 1, round(value["x"] * self.image.width)),
            min(self.image.height - 1, round(value["y"] * self.image.height)),
        )
