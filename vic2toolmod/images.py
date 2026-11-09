"""Game images for the GUI: Targa and DirectDraw files to PNG (standard library only).

Victoria 2 event pictures (``gfx/pictures/events/*.tga``) are 24- or 32-bit
true-colour Targa files, uncompressed (type 2) or run-length encoded (type 10).
Interface graphics (``gfx/interface/*.dds``) are DDS files, uncompressed
(``crime_strip.dds``: 32-bit ARGB) or compressed with DXT1 / DXT3 / DXT5.
Icon strips hold several frames side by side (`frame`).
"""

from __future__ import annotations

import struct
import zlib


class ImageError(ValueError):
    """The image is not in a supported format."""


def tga_to_rgba(data: bytes) -> tuple[int, int, bytes]:
    """Decode a true-colour Targa image.

    Returns:
        Width, height and the pixels as RGBA rows from the top.

    Raises:
        ImageError: For colour-mapped, grey or other unsupported Targa files.
    """
    if len(data) < 18:
        raise ImageError("too short for a Targa file")
    id_len, cmap_type, img_type = data[0], data[1], data[2]
    width, height, bpp, desc = struct.unpack_from("<HHBB", data, 12)
    if cmap_type != 0 or img_type not in (2, 10) or bpp not in (24, 32):
        raise ImageError(f"unsupported Targa (type {img_type}, {bpp} bits)")
    step = bpp // 8
    pos = 18 + id_len
    count = width * height
    out = bytearray(count * 4)
    i = 0

    def put(px: bytes) -> None:
        nonlocal i
        b, g, r = px[0], px[1], px[2]
        a = px[3] if step == 4 else 255
        out[i * 4 : i * 4 + 4] = bytes((r, g, b, a))
        i += 1

    if img_type == 2:
        for _ in range(count):
            put(data[pos : pos + step])
            pos += step
    else:
        while i < count:
            header = data[pos]
            pos += 1
            n = (header & 0x7F) + 1
            if header & 0x80:
                px = data[pos : pos + step]
                pos += step
                for _ in range(min(n, count - i)):
                    put(px)
            else:
                for _ in range(min(n, count - i)):
                    put(data[pos : pos + step])
                    pos += step
    row = width * 4
    if not desc & 0x20:  # origin at the bottom: flip
        rows = [out[y * row : (y + 1) * row] for y in range(height)]
        out = bytearray(b"".join(reversed(rows)))
    return width, height, bytes(out)


def png(width: int, height: int, rgba: bytes) -> bytes:
    """Encode RGBA pixels (rows from the top) as a PNG file."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    row = width * 4
    raw = b"".join(b"\x00" + rgba[y * row : (y + 1) * row] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def tga_to_png(data: bytes) -> bytes:
    """Convert a Targa file to PNG."""
    return png(*tga_to_rgba(data))


def dds_to_rgba(data: bytes) -> tuple[int, int, bytes]:
    """Decode the first image of a DDS file (uncompressed RGB(A), DXT1, DXT3, DXT5).

    Returns:
        Width, height and the pixels as RGBA rows from the top.

    Raises:
        ImageError: For other formats (DX10 headers, cube maps' extra faces are ignored).
    """
    if len(data) < 128 or data[:4] != b"DDS ":
        raise ImageError("not a DDS file")
    height, width = struct.unpack_from("<II", data, 12)
    pf_flags, fourcc, bits, rmask, gmask, bmask, amask = struct.unpack_from("<I4s5I", data, 80)
    body = data[128:]
    if pf_flags & 0x4:  # FourCC: compressed
        kind = fourcc.decode("latin-1")
        if kind not in ("DXT1", "DXT3", "DXT5"):
            raise ImageError(f"unsupported DDS compression {kind!r}")
        return width, height, _dxt(body, width, height, kind)
    if not pf_flags & 0x40 or bits not in (16, 24, 32):
        raise ImageError(f"unsupported DDS pixel format (flags {pf_flags:#x}, {bits} bits)")
    step = bits // 8
    has_alpha = bool(pf_flags & 0x1) and amask != 0
    need = width * height * step
    if len(body) < need:
        raise ImageError("DDS file is cut short")

    def channel(mask: int) -> tuple[int, int]:
        if not mask:
            return 0, 0
        shift = (mask & -mask).bit_length() - 1
        return shift, (mask >> shift)

    chans = [channel(m) for m in (rmask, gmask, bmask, amask if has_alpha else 0)]
    out = bytearray(width * height * 4)
    for i in range(width * height):
        v = int.from_bytes(body[i * step : (i + 1) * step], "little")
        o = i * 4
        for c, (shift, top) in enumerate(chans):
            if top:
                out[o + c] = ((v >> shift) & top) * 255 // top
            else:
                out[o + c] = 255 if c == 3 else 0
    return width, height, bytes(out)


def _rgb565(c: int) -> tuple[int, int, int]:
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31


def _dxt(body: bytes, width: int, height: int, kind: str) -> bytes:
    out = bytearray(width * height * 4)
    block = 8 if kind == "DXT1" else 16
    bw, bh = max(1, (width + 3) // 4), max(1, (height + 3) // 4)
    if len(body) < bw * bh * block:
        raise ImageError("DDS file is cut short")
    pos = 0
    for by in range(bh):
        for bx in range(bw):
            alpha = [255] * 16
            if kind == "DXT3":
                bits = int.from_bytes(body[pos : pos + 8], "little")
                alpha = [((bits >> (4 * i)) & 15) * 17 for i in range(16)]
                pos += 8
            elif kind == "DXT5":
                a0, a1 = body[pos], body[pos + 1]
                bits = int.from_bytes(body[pos + 2 : pos + 8], "little")
                if a0 > a1:
                    table = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
                else:
                    table = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)]
                    table += [0, 255]
                alpha = [table[(bits >> (3 * i)) & 7] for i in range(16)]
                pos += 8
            c0, c1, idx = struct.unpack_from("<HHI", body, pos)
            pos += 8
            p0, p1 = _rgb565(c0), _rgb565(c1)
            if kind != "DXT1" or c0 > c1:
                colors = [
                    (*p0, 255),
                    (*p1, 255),
                    (*((2 * a + b) // 3 for a, b in zip(p0, p1, strict=True)), 255),
                    (*((a + 2 * b) // 3 for a, b in zip(p0, p1, strict=True)), 255),
                ]
            else:
                colors = [
                    (*p0, 255),
                    (*p1, 255),
                    (*((a + b) // 2 for a, b in zip(p0, p1, strict=True)), 255),
                    (0, 0, 0, 0),
                ]
            for i in range(16):
                x, y = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if x >= width or y >= height:
                    continue
                r, g, b, a = colors[(idx >> (2 * i)) & 3]
                o = (y * width + x) * 4
                out[o : o + 4] = bytes((r, g, b, a if kind == "DXT1" else alpha[i]))
    return bytes(out)


def image_to_rgba(data: bytes) -> tuple[int, int, bytes]:
    """Decode a DDS or Targa file (by its content)."""
    if data[:4] == b"DDS ":
        return dds_to_rgba(data)
    return tga_to_rgba(data)


def frame(width: int, height: int, rgba: bytes, frames: int, index: int) -> tuple[int, int, bytes]:
    """One frame of an icon strip (frames side by side; ``index`` from 1)."""
    if frames <= 1:
        return width, height, rgba
    if not 1 <= index <= frames:
        raise ImageError(f"frame {index} is outside 1..{frames}")
    fw = width // frames
    x0 = (index - 1) * fw * 4
    row = width * 4
    pixels = b"".join(rgba[y * row + x0 : y * row + x0 + fw * 4] for y in range(height))
    return fw, height, pixels
