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

import re
import struct
from dataclasses import dataclass
from typing import Any

from vic2toolmod.analysis.world import World
from vic2toolmod.images import ImageError, png
from vic2toolmod.script.cst import Assignment, Block, Scalar
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


_RUN = re.compile(rb"(...)\1*", re.S)


def province_colors(ws: Workspace) -> dict[bytes, int]:
    """RGB bytes -> province id (``map/definition.csv``)."""
    out: dict[bytes, int] = {}
    f = ws.file("map/definition.csv")
    if f is None:
        return out
    for line in f.path.read_bytes().decode("latin-1").splitlines():
        parts = line.split(";")
        if len(parts) >= 4 and parts[0].strip().isdigit():
            try:
                out[bytes((int(parts[1]), int(parts[2]), int(parts[3])))] = int(parts[0])
            except ValueError:
                continue
    return out


def adjacency(ws: Workspace) -> dict[int, set[int]]:
    """Provinces that touch on the map, with the straits of ``map/adjacencies.csv``.

    ``map/provinces.bmp`` wraps east-west; ``impassable`` adjacencies are taken away.
    Rows are split into runs of one colour (a regular expression does it in C, RPM:
    0.3 s); neighbouring runs of a row and overlapping runs of two rows touch.
    """
    f = ws.file("map/provinces.bmp")
    if f is None:
        return {}
    width, height, rgb = read_bmp(f.path.read_bytes())
    ids = province_colors(ws)
    pairs: set[tuple[bytes, bytes]] = set()

    def add(a: bytes, b: bytes) -> None:
        if a != b:
            pairs.add((a, b) if a < b else (b, a))

    prev: list[tuple[int, int, bytes]] = []
    row_len = width * 3
    for y in range(height):
        row = rgb[y * row_len : (y + 1) * row_len]
        runs = [(m.start() // 3, m.end() // 3, m.group(1)) for m in _RUN.finditer(row)]
        for left, right in zip(runs, runs[1:], strict=False):
            add(left[2], right[2])
        if runs:
            add(runs[0][2], runs[-1][2])  # the map wraps around
        i = j = 0
        while i < len(prev) and j < len(runs):
            pa, ra = prev[i], runs[j]
            if pa[0] < ra[1] and ra[0] < pa[1]:
                add(pa[2], ra[2])
            if pa[1] < ra[1]:
                i += 1
            else:
                j += 1
        prev = runs
    out: dict[int, set[int]] = {}
    for ca, cb in pairs:
        ia, ib = ids.get(ca), ids.get(cb)
        if ia and ib:
            out.setdefault(ia, set()).add(ib)
            out.setdefault(ib, set()).add(ia)
    adj = ws.file("map/adjacencies.csv")
    if adj is not None:
        for line in adj.path.read_bytes().decode("latin-1").splitlines():
            parts = line.split(";")
            if len(parts) < 3 or not parts[0].strip().isdigit() or not parts[1].strip().isdigit():
                continue
            a, b, kind = int(parts[0]), int(parts[1]), parts[2].strip().lower()
            if kind == "impassable":
                out.get(a, set()).discard(b)
                out.get(b, set()).discard(a)
            else:
                out.setdefault(a, set()).add(b)
                out.setdefault(b, set()).add(a)
    return out


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


def _second_level_colors(ws: Workspace, rel: str) -> dict[str, list[int]]:
    """``group = { name = { color = { r g b } } }`` -> name -> colour (0..1 become 0..255)."""
    out: dict[str, list[int]] = {}
    f = ws.file(rel)
    if f is None:
        return out
    for group in ws.document(f.rel).items:
        if not (isinstance(group, Assignment) and isinstance(group.value, Block)):
            continue
        for item in group.value.items:
            if not (isinstance(item, Assignment) and isinstance(item.value, Block)):
                continue
            color = item.value.find("color")
            if color is None or not isinstance(color.value, Block):
                continue
            try:
                nums = [float(i.value) for i in color.value.items if isinstance(i, Scalar)][:3]
            except ValueError:
                continue
            if len(nums) == 3:
                floats = all(n <= 1 for n in nums) and any("." in str(n) for n in nums)
                out[item.key_text.lower()] = [
                    max(0, min(255, round(n * 255 if floats else n))) for n in nums
                ]
    return out


def _main(pops: list[Any], attr: str) -> str:
    sizes: dict[str, float] = {}
    for p in pops:
        sizes[getattr(p, attr)] = sizes.get(getattr(p, attr), 0) + p.size
    return max(sizes, key=lambda k: sizes[k]) if sizes else ""


def info(ws: Workspace, world: World) -> dict[str, Any]:
    """Provinces and the colours of countries, cultures and religions.

    Each province: colour, name, owner, controller, cores, main culture and
    religion of its pops, trade goods, terrain, continent and pop count.
    """
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
            pops = world.pops.get(pid, [])
            provinces[pid] = {
                "rgb": rgb,
                "name": parts[4].strip() if len(parts) > 4 else "",
                "owner": p.owner if p else "",
                "controller": (p.controller or p.owner) if p else "",
                "cores": sorted(p.cores) if p else [],
                "land": p is not None,  # has a history file (sea and lakes have none)
                "culture": _main(pops, "culture"),
                "religion": _main(pops, "religion"),
                "trade_goods": p.values.get("trade_goods", "") if p else "",
                "terrain": p.values.get("terrain", "") if p else "",
                "continent": world.continent.get(pid, ""),
                "pops": round(sum(x.size for x in pops)),
            }
    return {
        "provinces": provinces,
        "colors": country_colors(ws),
        "culture_colors": _second_level_colors(ws, "common/cultures.txt"),
        "religion_colors": _second_level_colors(ws, "common/religion.txt"),
        # owners' facts for the map's colours (K98 C)
        "countries": {
            tag: {
                "prestige": float(c.values.get("prestige", 0) or 0),
                "government": c.values.get("government", ""),
                "civilized": c.values.get("civilized", "no") == "yes",
            }
            for tag, c in world.countries.items()
        },
    }


def province(ws: Workspace, world: World, pid: int) -> dict[str, Any]:
    """One province at the date: its history values, cores, pops and history file."""
    p = world.provinces.get(pid)
    rel = next(
        (
            f.rel
            for low, f in sorted(ws.project.files().items())
            if re.match(rf"history/provinces/[^/]+/{pid}(?!\d)", low)
        ),
        None,
    )
    pops = world.pops.get(pid, [])
    return {
        "id": pid,
        "file": rel,
        "owner": p.owner if p else "",
        "controller": (p.controller or p.owner) if p else "",
        "cores": sorted(p.cores) if p else [],
        "values": dict(sorted(p.values.items())) if p else {},
        "pops": [
            {
                "type": x.type,
                "culture": x.culture,
                "religion": x.religion,
                "size": x.size,
                "militancy": x.militancy,
            }
            for x in sorted(pops, key=lambda x: -x.size)
        ],
        "neighbours": sorted((world.neighbours or {}).get(pid, set())),
    }
