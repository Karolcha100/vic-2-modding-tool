"""Game images for the GUI: Targa (``.tga``) to PNG with the standard library only.

Victoria 2 event pictures (``gfx/pictures/events/*.tga``) are 24- or 32-bit
true-colour Targa files, uncompressed (type 2) or run-length encoded (type 10).
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
