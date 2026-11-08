"""Check that reading, parsing and writing a file gives back the same bytes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from vic2toolmod import textio
from vic2toolmod.script.cst import Document
from vic2toolmod.script.parser import parse_text


@dataclass(frozen=True, slots=True)
class RoundtripResult:
    """Outcome of a lossless read/parse/write cycle for one file.

    Attributes:
        path: The file.
        ok: Whether the written bytes equal the original bytes.
        size: File size in bytes.
        encoding: Detected encoding.
        parse_seconds: Time spent tokenizing and parsing.
        first_difference: Byte offset of the first difference (``None`` if ok).
        document: The parsed document.
    """

    path: Path
    ok: bool
    size: int
    encoding: textio.Encoding
    parse_seconds: float
    first_difference: int | None
    document: Document


def check_file(path: str | Path) -> RoundtripResult:
    """Read, parse and re-encode a file, comparing with the original bytes.

    Args:
        path: File to check.

    Returns:
        The result (never raises for content problems).
    """
    path = Path(path)
    data = path.read_bytes()
    text, encoding = textio.decode(data)
    started = time.perf_counter()
    doc = parse_text(text)
    elapsed = time.perf_counter() - started
    out = textio.encode(doc.to_text(), encoding)
    diff = None
    if out != data:
        diff = next(
            (i for i, (a, b) in enumerate(zip(out, data, strict=False)) if a != b),
            min(len(out), len(data)),
        )
    return RoundtripResult(path, diff is None, len(data), encoding, elapsed, diff, doc)
