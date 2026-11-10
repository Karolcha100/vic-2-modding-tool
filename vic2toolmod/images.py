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
    if cmap_type != 0 or img_type not in (2, 10) or bpp not in (16, 24, 32):
        raise ImageError(f"unsupported Targa (type {img_type}, {bpp} bits)")
    step = bpp // 8
    pos = 18 + id_len
    count = width * height
    out = bytearray(count * 4)
    i = 0

    def put(px: bytes) -> None:
        nonlocal i
        if step == 2:  # A1 R5 G5 B5, little endian (alpha ignored: often unset)
            v = px[0] | px[1] << 8
            r, g, b = ((v >> s & 31) * 255 // 31 for s in (10, 5, 0))
            a = 255
        else:
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
    if pf_flags & 0x20 and bits == 8:  # 8-bit palette (RPM's decision pictures)
        # 256 entries of R G B flags after the header, then one index per pixel
        if len(body) < 1024 + width * height:
            raise ImageError("DDS file is cut short")
        palette = [bytes((body[i * 4], body[i * 4 + 1], body[i * 4 + 2], 255)) for i in range(256)]
        indices = body[1024 : 1024 + width * height]
        return width, height, b"".join(palette[i] for i in indices)
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


# -- writing (K94: bigger window backgrounds) ------------------------------------------
def dds(width: int, height: int, rgba: bytes) -> bytes:
    """An uncompressed 32-bit DDS file (A8R8G8B8, one image), as the game reads it."""
    header = bytearray(128)
    header[:4] = b"DDS "
    # size, flags (caps | height | width | pitch | pixel format), height, width, pitch
    struct.pack_into("<IIIII", header, 4, 124, 0x100F, height, width, width * 4)
    # pixel format: size, flags (RGB | alpha), FourCC, bits, R G B A masks
    struct.pack_into(
        "<II4s5I", header, 76, 32, 0x41, b"\0\0\0\0", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000
    )
    struct.pack_into("<I", header, 108, 0x1000)  # caps: texture
    body = bytearray(len(rgba))
    body[0::4] = rgba[2::4]  # B
    body[1::4] = rgba[1::4]  # G
    body[2::4] = rgba[0::4]  # R
    body[3::4] = rgba[3::4]  # A
    return bytes(header) + bytes(body)


def tga(width: int, height: int, rgba: bytes) -> bytes:
    """An uncompressed 32-bit Targa file, rows from the top."""
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, width, height, 32, 0x28)
    body = bytearray(len(rgba))
    body[0::4] = rgba[2::4]
    body[1::4] = rgba[1::4]
    body[2::4] = rgba[0::4]
    body[3::4] = rgba[3::4]
    return header + bytes(body)


def _axis(size: int, new: int, before: int, after: int) -> list[tuple[int, int, float]]:
    """For each new pixel: two source pixels and the weight of the second.

    The first ``before`` and last ``after`` pixels are copied as they are; the
    part between them is stretched (linear interpolation).
    """
    b0 = max(0, min(before, size - 1, new))
    b1 = max(0, min(after, size - b0 - 1, new - b0))
    out: list[tuple[int, int, float]] = []
    inner, new_inner = size - b0 - b1, new - b0 - b1
    for i in range(new):
        if i < b0:
            out.append((i, i, 0.0))
        elif i >= new - b1:
            j = size - (new - i)
            out.append((j, j, 0.0))
        else:
            # the centre of new pixel i, mapped into the source's inner part
            f = (i - b0 + 0.5) * inner / max(new_inner, 1) - 0.5
            f = min(max(f, 0.0), inner - 1.0)
            j0 = int(f)
            j1 = min(j0 + 1, inner - 1)
            out.append((b0 + j0, b0 + j1, f - j0))
    return out


Border = int | tuple[int, int, int, int]
"""Pixels kept as they are: the same at every edge, or ``(left, top, right, bottom)``."""


def stretch(width: int, height: int, rgba: bytes, new_w: int, new_h: int, border: Border) -> bytes:
    """Resize a picture with its frame kept ("nine-slice").

    The corners stay as they are, the edges stretch along their length and the
    middle in both directions. ``border`` is the frame: one number for every
    edge (at most half the picture), or ``(left, top, right, bottom)`` - e.g. a
    large left edge keeps the left part of a background (a panel drawn into it)
    and stretches only the rest (T017).
    """
    if new_w < 1 or new_h < 1:
        raise ImageError("the new size must be at least 1×1")
    if isinstance(border, int):
        bx = max(0, min(border, width // 2, new_w // 2))
        by = max(0, min(border, height // 2, new_h // 2))
        left, top, right, bottom = bx, by, bx, by
    else:
        left, top, right, bottom = border
    cols = _axis(width, new_w, left, right)
    rows = _axis(height, new_h, top, bottom)
    row = width * 4
    # horizontal pass: every source row at the new width
    wide: list[bytes] = []
    for y in range(height):
        src = rgba[y * row : (y + 1) * row]
        out = bytearray(new_w * 4)
        for x, (a, b, t) in enumerate(cols):
            pa, pb = a * 4, b * 4
            if t == 0.0:
                out[x * 4 : x * 4 + 4] = src[pa : pa + 4]
            else:
                for c in range(4):
                    out[x * 4 + c] = int(src[pa + c] + (src[pb + c] - src[pa + c]) * t + 0.5)
        wide.append(bytes(out))
    # vertical pass
    result = bytearray()
    for a, b, t in rows:
        if t == 0.0:
            result += wide[a]
        else:
            ra, rb = wide[a], wide[b]
            result += bytes(int(p + (q - p) * t + 0.5) for p, q in zip(ra, rb, strict=True))
    return bytes(result)


def shrink(width: int, height: int, rgba: bytes, max_w: int) -> tuple[int, int, bytes]:
    """A small copy for a preview (nearest pixel), at most ``max_w`` wide."""
    if width <= max_w:
        return width, height, rgba
    k = width / max_w
    new_h = max(1, int(height / k))
    out = bytearray()
    for y in range(new_h):
        sy = min(height - 1, int(y * k))
        line = rgba[sy * width * 4 : (sy + 1) * width * 4]
        for x in range(max_w):
            sx = min(width - 1, int(x * k)) * 4
            out += line[sx : sx + 4]
    return max_w, new_h, bytes(out)
