from pathlib import Path

from vic2toolmod.config import load_settings


def test_file_and_env(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('game_dir = "/games/v2"\nmod_dirs = ["/mods/a", "/mods/b"]\n')
    monkeypatch.delenv("VIC2_GAME_DIR", raising=False)
    monkeypatch.delenv("VIC2_MOD_DIR", raising=False)
    s = load_settings(cfg)
    assert s.game_dir == Path("/games/v2")
    assert s.mod_dirs == (Path("/mods/a"), Path("/mods/b"))
    monkeypatch.setenv("VIC2_GAME_DIR", "/env/game")
    monkeypatch.setenv("VIC2_MOD_DIR", "/env/m1")
    s = load_settings(cfg)
    assert s.game_dir == Path("/env/game")
    assert s.mod_dirs == (Path("/env/m1"),)


def test_missing_file(tmp_path, monkeypatch):
    monkeypatch.delenv("VIC2_GAME_DIR", raising=False)
    monkeypatch.delenv("VIC2_MOD_DIR", raising=False)
    s = load_settings(tmp_path / "nope.toml")
    assert s.game_dir is None and s.mod_dirs == ()
