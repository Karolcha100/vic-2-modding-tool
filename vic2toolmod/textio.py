r"""Reading and writing game files without losing a single byte.

Victoria 2 reads its script files as Windows-1252. Some mods also contain
UTF-8 files (with or without a byte order mark). This module detects the
encoding of a file, decodes it to ``str`` and encodes it back so that an
unchanged text always produces the original bytes.

Windows-1252 leaves five byte values undefined (0x81, 0x8D, 0x8F, 0x90, 0x9D).
Python's ``cp1252`` codec rejects them, but real mod files contain them, so
the ``CP1252`` encoding used here maps each of them to the code point with the
same number (U+0081 …). Line endings are never touched: ``\r\n``, ``\n`` and
``\r`` stay exactly as they were.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

UTF8_BOM = b"\xef\xbb\xbf"

_UNDEFINED_CP1252 = (0x81, 0x8D, 0x8F, 0x90, 0x9D)


def _build_tables() -> tuple[dict[int, int], dict[int, int]]:
    """Build translation tables between Latin-1 and lossless Windows-1252."""
    decode: dict[int, int] = {}
    for byte in range(0x80, 0xA0):
        char = chr(byte) if byte in _UNDEFINED_CP1252 else bytes([byte]).decode("cp1252")
        decode[byte] = ord(char)
    encode = {cp: byte for byte, cp in decode.items() if cp != byte}
    # A C1 control character typed by a user would be written as a byte that
    # decodes to a different character, so only the five undefined ones may
    # pass through unchanged.
    for byte in range(0x80, 0xA0):
        if byte not in _UNDEFINED_CP1252:
            encode.setdefault(byte, 0x100)  # 0x100 = "not encodable" marker
    return {k: v for k, v in decode.items() if k != v}, encode


_DECODE_TABLE, _ENCODE_TABLE = _build_tables()
_NOT_LATIN1 = re.compile(r"[^\x00-\xff]")


class Encoding(StrEnum):
    """Encodings a script file can have."""

    CP1252 = "cp1252"
    """Windows-1252 (with the five undefined bytes passed through)."""
    UTF8 = "utf-8"
    """UTF-8 without a byte order mark."""
    UTF8_BOM = "utf-8-bom"
    """UTF-8 with a byte order mark (the mark is not part of the text)."""


class EncodingError(ValueError):
    """Text contains a character that the target encoding cannot store.

    Attributes:
        offset: Index of the first offending character in the text.
        char: The offending character.
        encoding: The encoding that cannot store it.
    """

    def __init__(self, offset: int, char: str, encoding: Encoding) -> None:
        super().__init__(
            f"character {char!r} (U+{ord(char):04X}) at offset {offset} "
            f"cannot be written as {encoding.value}"
        )
        self.offset = offset
        self.char = char
        self.encoding = encoding


def detect_encoding(data: bytes) -> Encoding:
    """Guess the encoding of raw file contents.

    Rules: a UTF-8 byte order mark means UTF-8; pure ASCII and anything that
    is not valid UTF-8 mean Windows-1252 (the game's encoding); non-ASCII data
    that is valid UTF-8 means UTF-8.

    Args:
        data: Raw file contents.

    Returns:
        The detected encoding.
    """
    if data.startswith(UTF8_BOM):
        return Encoding.UTF8_BOM
    if data.isascii():
        return Encoding.CP1252
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return Encoding.CP1252
    return Encoding.UTF8


def decode(data: bytes, encoding: Encoding | None = None) -> tuple[str, Encoding]:
    """Decode file contents losslessly.

    Args:
        data: Raw file contents.
        encoding: Encoding to use; detected with `detect_encoding` when omitted.

    Returns:
        The text and the encoding that was used.

    Raises:
        UnicodeDecodeError: If ``encoding`` is a UTF-8 variant and the data is
            not valid UTF-8.
    """
    if encoding is None:
        encoding = detect_encoding(data)
    if encoding is Encoding.CP1252:
        return data.decode("latin-1").translate(_DECODE_TABLE), encoding
    if encoding is Encoding.UTF8_BOM:
        body = data[len(UTF8_BOM) :] if data.startswith(UTF8_BOM) else data
        return body.decode("utf-8"), encoding
    return data.decode("utf-8"), encoding


def encode(text: str, encoding: Encoding) -> bytes:
    """Encode text back to bytes; the inverse of `decode`.

    Args:
        text: Text to encode.
        encoding: Target encoding.

    Returns:
        The encoded bytes.

    Raises:
        EncodingError: If the text contains a character the encoding cannot
            store (for Windows-1252, e.g. Polish ``ł``).
    """
    if encoding is Encoding.UTF8_BOM:
        return UTF8_BOM + text.encode("utf-8")
    if encoding is Encoding.UTF8:
        return text.encode("utf-8")
    translated = text.translate(_ENCODE_TABLE)
    bad = _NOT_LATIN1.search(translated)
    if bad is not None:
        offset = bad.start()
        raise EncodingError(offset, text[offset], encoding)
    return translated.encode("latin-1")


@dataclass(frozen=True, slots=True)
class SourceText:
    """Decoded contents of a file together with what is needed to write it back.

    Attributes:
        text: The decoded text (line endings unchanged).
        encoding: Encoding the file had.
        path: Where the text came from, if it came from a file.
    """

    text: str
    encoding: Encoding
    path: Path | None = None

    def to_bytes(self) -> bytes:
        """Encode the text in its original encoding."""
        return encode(self.text, self.encoding)


def read_source(path: str | Path) -> SourceText:
    """Read a file and decode it losslessly.

    Args:
        path: File to read.

    Returns:
        The decoded file.
    """
    path = Path(path)
    text, encoding = decode(path.read_bytes())
    return SourceText(text, encoding, path)


def write_source(path: str | Path, text: str, encoding: Encoding) -> None:
    """Encode text and write it to a file.

    The text is encoded before the file is opened, so an `EncodingError`
    leaves the file untouched.

    Args:
        path: File to write.
        text: Text to write.
        encoding: Encoding to write it in.
    """
    data = encode(text, encoding)
    Path(path).write_bytes(data)
