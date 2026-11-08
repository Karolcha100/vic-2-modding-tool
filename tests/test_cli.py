import json

from vic2toolmod.cli import main


def test_parse_outline(tmp_path, capsys):
    f = tmp_path / "e.txt"
    f.write_bytes(b"a = { b = 1 }\n")
    assert main(["parse", str(f)]) == 0
    out = capsys.readouterr().out
    assert "a = {" in out and "b = 1" in out


def test_parse_json(tmp_path, capsys):
    f = tmp_path / "e.txt"
    f.write_bytes(b"a = {\n")
    assert main(["parse", "--json", str(f)]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["encoding"] == "cp1252"
    assert data["diagnostics"][0]["code"] == "syntax.unclosed-brace"


def test_roundtrip_and_errors(tmp_path, capsys):
    (tmp_path / "ok.txt").write_bytes(b"a = 1\r\n")
    (tmp_path / "bad.gui").write_bytes(b"a = {\n")
    (tmp_path / "ignored.csv").write_bytes(b"x;y")
    assert main(["roundtrip", str(tmp_path)]) == 0
    assert "2 files" in capsys.readouterr().out
    assert main(["errors", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "bad.gui:1:5: error syntax.unclosed-brace" in out
