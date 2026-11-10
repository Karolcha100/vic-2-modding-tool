"""The province map (K75 A, first part; asked for in the country creator, @A6).

``map/provinces.bmp`` paints every province in its own colour, and
``map/definition.csv`` says which colour is which province. `id_image` gives
that picture as PNG, made smaller by ``scale`` (every ``scale``-th pixel, so
colours stay exact), and `info` the colours, names, owners and cores at a date
(from `world.World`) and the countries' map colours. The browser paints the
map from these (owner colours, chosen provinces) and finds the province under
the mouse by its colour.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from vic2toolmod.analysis.world import World
from vic2toolmod.images import ImageError, png
from vic2toolmod.script.cst import Block, Scalar
from vic2toolmod.workspace import Workspace


def read_bmp(data: bytes) -> tuple[int, int, bytes]:
    """An uncompressed 24-bit map BMP as ``(width, height, RGB rows, north first)``."""
    if data[:2] != b"BM" or len(data) < 54:
        raise ImageError("not a BMP file")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bits, compression = struct.unpack_from("<HI", data, 28)
    if bits != 24 or compression != 0:
        raise ImageError(f"only uncompressed 24-bit BMP is read (this one: {bits} bit)")
    # Paradox's map pictures keep north in the first stored row although the
    # header says "from the bottom": the game's own coordinates (map/positions.txt,
    # y up from the south) only match when the rows are taken in stored order.
    height = abs(height)
    stride = (width * 3 + 3) & ~3
    rows = []
    for y in range(height):
        src = y
        start = offset + src * stride
        row = data[start : start + width * 3]
        rgb = bytearray(len(row))
        rgb[0::3], rgb[1::3], rgb[2::3] = row[2::3], row[1::3], row[0::3]  # BGR -> RGB
        rows.append(bytes(rgb))
    return width, height, b"".join(rows)


@dataclass
class IdImage:
    """The province picture, smaller by ``scale``."""

    width: int
    height: int
    scale: int
    png: bytes


def id_image(ws: Workspace, scale: int = 2) -> IdImage:
    """``map/provinces.bmp`` as PNG, every ``scale``-th pixel (exact province colours)."""
    f = ws.file("map/provinces.bmp")
    if f is None:
        raise ImageError("map/provinces.bmp not found")
    width, height, rgb = read_bmp(f.path.read_bytes())
    w, h = (width + scale - 1) // scale, (height + scale - 1) // scale
    out = bytearray(w * h * 4)
    out[3::4] = b"\xff" * (w * h)
    for y in range(h):
        row = rgb[y * scale * width * 3 : (y * scale + 1) * width * 3]
        line = bytearray(w * 3)
        for c in range(3):
            line[c::3] = row[c :: 3 * scale][:w]
        base = y * w * 4
        target = out[base : base + w * 4]
        target[0::4], target[1::4], target[2::4] = line[0::3], line[1::3], line[2::3]
        out[base : base + w * 4] = target
    return IdImage(w, h, scale, png(w, h, bytes(out)))


def country_colors(ws: Workspace) -> dict[str, list[int]]:
    """Tag -> map colour from ``common/countries/<file>`` (``color = { r g b }``)."""
    out: dict[str, list[int]] = {}
    lf = ws.file("common/countries.txt")
    if lf is None:
        return out
    for entry in ws.document(lf.rel).assignments():
        if not isinstance(entry.value, Scalar):
            continue
        cf = ws.file("common/" + entry.value.value.strip('"'))
        if cf is None:
            continue
        color = ws.document(cf.rel).find("color")
        if color is not None and isinstance(color.value, Block):
            nums = [i.value for i in color.value.items if isinstance(i, Scalar)]
            try:
                rgb = [max(0, min(255, round(float(n)))) for n in nums[:3]]
            except ValueError:
                continue
            if len(rgb) == 3:
                out[entry.key_text.upper()] = rgb
    return out


def info(ws: Workspace, world: World) -> dict[str, Any]:
    """Province colours, names, owners and cores, and the countries' colours."""
    provinces: dict[int, dict[str, Any]] = {}
    f = ws.file("map/definition.csv")
    if f is not None:
        for line in f.path.read_bytes().decode("latin-1").splitlines():
            parts = line.split(";")
            if len(parts) < 4 or not parts[0].strip().isdigit():
                continue
            try:
                rgb = [int(parts[1]), int(parts[2]), int(parts[3])]
            except ValueError:
                continue
            pid = int(parts[0])
            p = world.provinces.get(pid)
            provinces[pid] = {
                "rgb": rgb,
                "name": parts[4].strip() if len(parts) > 4 else "",
                "owner": p.owner if p else "",
                "cores": sorted(p.cores) if p else [],
                "land": p is not None,  # has a history file (sea and lakes have none)
            }
    return {"provinces": provinces, "colors": country_colors(ws)}
