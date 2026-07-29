from __future__ import annotations

import math

from .png_codec import PngImage


Color = tuple[int, int, int, int]


class RasterCanvas:
    def __init__(self, image: PngImage):
        self.image = image

    def blend(self, x: int, y: int, color: Color) -> None:
        if not (0 <= x < self.image.width and 0 <= y < self.image.height):
            return
        offset = (y * self.image.width + x) * 4
        alpha = color[3]
        inverse = 255 - alpha
        for channel in range(3):
            old = self.image.pixels[offset + channel]
            value = (color[channel] * alpha + old * inverse) // 255
            self.image.pixels[offset + channel] = value
        self.image.pixels[offset + 3] = 255

    def brush(self, x: int, y: int, color: Color, width: int) -> None:
        radius = max(0, width // 2)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    self.blend(x + dx, y + dy, color)

    def line(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        color: Color,
        width: int,
    ) -> None:
        x1, y1 = start
        x2, y2 = end
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for step in range(steps + 1):
            ratio = step / steps
            x = round(x1 + (x2 - x1) * ratio)
            y = round(y1 + (y2 - y1) * ratio)
            self.brush(x, y, color, width)

    def rect(
        self,
        bounds: tuple[int, int, int, int],
        color: Color,
        width: int,
    ) -> None:
        left, top, right, bottom = bounds
        self.line((left, top), (right, top), color, width)
        self.line((right, top), (right, bottom), color, width)
        self.line((right, bottom), (left, bottom), color, width)
        self.line((left, bottom), (left, top), color, width)

    def fill_rect(
        self,
        bounds: tuple[int, int, int, int],
        color: Color,
    ) -> None:
        left, top, right, bottom = bounds
        for y in range(top, bottom + 1):
            for x in range(left, right + 1):
                self.blend(x, y, color)

    def ellipse(
        self,
        bounds: tuple[int, int, int, int],
        color: Color,
        width: int,
    ) -> None:
        left, top, right, bottom = bounds
        cx, cy = (left + right) / 2, (top + bottom) / 2
        rx, ry = max(1, (right - left) / 2), max(1, (bottom - top) / 2)
        points = max(48, round(math.pi * (rx + ry)))
        previous = (round(cx + rx), round(cy))
        for step in range(1, points + 1):
            angle = 2 * math.pi * step / points
            current = (
                round(cx + rx * math.cos(angle)),
                round(cy + ry * math.sin(angle)),
            )
            self.line(previous, current, color, width)
            previous = current

    def fill_ellipse(
        self,
        bounds: tuple[int, int, int, int],
        color: Color,
    ) -> None:
        left, top, right, bottom = bounds
        cx, cy = (left + right) / 2, (top + bottom) / 2
        rx, ry = max(1, (right - left) / 2), max(1, (bottom - top) / 2)
        for y in range(top, bottom + 1):
            span = rx * math.sqrt(max(0, 1 - ((y - cy) / ry) ** 2))
            for x in range(round(cx - span), round(cx + span) + 1):
                self.blend(x, y, color)

    def arrow(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        color: Color,
        width: int,
        head_length: float,
    ) -> None:
        self.line(start, end, color, width)
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        for offset in (-0.65, 0.65):
            point = (
                round(end[0] - head_length * math.cos(angle + offset)),
                round(end[1] - head_length * math.sin(angle + offset)),
            )
            self.line(end, point, color, width)

    def disc(self, x: int, y: int, radius: int, color: Color) -> None:
        for dy in range(-radius, radius + 1):
            span = round(math.sqrt(max(0, radius * radius - dy * dy)))
            for dx in range(-span, span + 1):
                self.blend(x + dx, y + dy, color)
