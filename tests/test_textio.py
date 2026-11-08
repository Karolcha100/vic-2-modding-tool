import pytest

from vic2toolmod import textio
from vic2toolmod.textio import Encoding, EncodingError


def test_every_byte_roundtrips_as_cp1252():
    data = bytes(range(256))
    text, encoding = textio.decode(data, Encoding.CP1252)
    assert encoding is Encoding.CP1252
    assert textio.encode(text, encoding) == data


def test_cp1252_characters_decode_properly():
    text, _ = textio.decode(b"caf\xe9 \x80 \x9c", Encoding.CP1252)
    assert text == "café € œ"


def test_undefined_cp1252_bytes_pass_through():
    text, _ = textio.decode(b"a\x81b\x9dc", Encoding.CP1252)
    assert text == "a\x81b\x9dc"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"plain ascii", Encoding.CP1252),
        (b"caf\xe9", Encoding.CP1252),
        ("café".encode(), Encoding.UTF8),
        (textio.UTF8_BOM + b"x = 1", Encoding.UTF8_BOM),
        (b"", Encoding.CP1252),
    ],
)
def test_detect_encoding(data, expected):
    assert textio.detect_encoding(data) is expected


def test_bom_is_not_part_of_text_but_is_written_back():
    data = textio.UTF8_BOM + "a = ł".encode()
    text, encoding = textio.decode(data)
    assert text == "a = ł"
    assert textio.encode(text, encoding) == data


def test_polish_letter_cannot_be_written_as_cp1252():
    with pytest.raises(EncodingError) as info:
        textio.encode("name = Łódź", Encoding.CP1252)
    assert info.value.offset == 7
    assert info.value.char == "Ł"


def test_c1_control_character_is_rejected():
    # U+0080 would be written as byte 0x80, which reads back as "€".
    with pytest.raises(EncodingError):
        textio.encode("x\x80", Encoding.CP1252)


def test_line_endings_untouched():
    data = b"a\r\nb\nc\rd"
    text, encoding = textio.decode(data)
    assert text == "a\r\nb\nc\rd"
    assert textio.encode(text, encoding) == data


def test_write_source_does_not_touch_file_on_error(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"old")
    with pytest.raises(EncodingError):
        textio.write_source(path, "ł", Encoding.CP1252)
    assert path.read_bytes() == b"old"


def test_read_and_write_source(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"a = caf\xe9\r\n")
    source = textio.read_source(path)
    assert source.text == "a = café\r\n"
    assert source.to_bytes() == path.read_bytes()
    textio.write_source(path, source.text + "b = 2\r\n", source.encoding)
    assert path.read_bytes() == b"a = caf\xe9\r\nb = 2\r\n"
