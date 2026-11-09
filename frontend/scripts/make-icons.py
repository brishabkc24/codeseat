"""Draws CodeSeat's app icons: the seat map, with one seat lit.

Run with any Python 3 from anywhere; it needs only the standard library and
writes into frontend/public. The colours are the theme's own tokens
(frontend/src/tokens.css), converted from oklch to sRGB here, and the hex
values it prints are the ones the manifest and the theme-color meta use.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public"

# (lightness %, chroma, hue) as written in tokens.css
PAPER = (9, 0.008, 75)  # --color-paper
SEAT = (50, 0.010, 80)  # --color-muted-2
LIT = (72, 0.17, 45)  # --color-accent

# Where the lit seat sits in the 3x3 map: row A (nearest the teacher), middle seat.
LIT_SEAT = (0, 1)


def srgb(lightness: float, chroma: float, hue: float) -> tuple[int, int, int]:
    """oklch to 8-bit sRGB, the standard matrices."""
    lum = lightness / 100
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = lum + 0.3963377774 * a + 0.2158037573 * b
    m_ = lum - 0.1055613458 * a - 0.0638541728 * b
    s_ = lum - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3
    linear = (
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )

    def gamma(value: float) -> int:
        value = min(1.0, max(0.0, value))
        encoded = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
        return round(encoded * 255)

    return tuple(gamma(channel) for channel in linear)  # type: ignore[return-value]


def hex_of(colour: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % colour


def png(size: int, rows: list[bytearray]) -> bytes:
    """An 8-bit RGB PNG from rows of packed pixels."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(row) for row in rows)  # each row starts with filter type 0
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def draw(size: int, span: int) -> bytes:
    """A square icon: paper all over, the seat map `span` pixels wide in the middle."""
    paper, seat, lit = (bytes(srgb(*token)) for token in (PAPER, SEAT, LIT))
    gap = round(span * 28 / 368)  # the map's own proportion of seat to aisle
    cell = (span - 2 * gap) // 3
    span = 3 * cell + 2 * gap
    origin = (size - span) // 2
    rows = [bytearray(paper * size) for _ in range(size)]
    for row in range(3):
        for col in range(3):
            colour = lit if (row, col) == LIT_SEAT else seat
            left = origin + col * (cell + gap)
            top = origin + row * (cell + gap)
            for y in range(top, top + cell):
                rows[y][left * 3 : (left + cell) * 3] = colour * cell
    return png(size, rows)


def favicon() -> str:
    """The same map as an SVG, crisp at 16 and 32 pixels."""
    paper, seat, lit = (hex_of(srgb(*token)) for token in (PAPER, SEAT, LIT))
    cell, gap, margin = 7, 3, 2.5
    squares = []
    for row in range(3):
        for col in range(3):
            colour = lit if (row, col) == LIT_SEAT else seat
            x = margin + col * (cell + gap)
            y = margin + row * (cell + gap)
            squares.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{colour}"/>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        f'<rect width="32" height="32" fill="{paper}"/>' + "".join(squares) + "</svg>\n"
    )


def main() -> None:
    icons = PUBLIC / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    # Maskable icons are cropped to a circle 80% wide, so their map stays well inside it.
    for path, size, span in [
        (icons / "icon-192.png", 192, 138),
        (icons / "icon-512.png", 512, 368),
        (icons / "icon-maskable-512.png", 512, 280),
        (PUBLIC / "apple-touch-icon.png", 180, 130),
    ]:
        path.write_bytes(draw(size, span))
        print(f"wrote {path.relative_to(PUBLIC.parent)} ({path.stat().st_size} bytes)")
    (PUBLIC / "favicon.svg").write_text(favicon(), encoding="utf-8")
    print("wrote public/favicon.svg")
    print("paper", hex_of(srgb(*PAPER)), "seat", hex_of(srgb(*SEAT)), "accent", hex_of(srgb(*LIT)))


if __name__ == "__main__":
    main()
