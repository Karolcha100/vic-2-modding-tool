"""Versions of the mod (T025): git commits or zip copies; save, list, compare, go to."""

import shutil
import subprocess

import pytest

from vic2toolmod.versions import CopyVersions, GitVersions, VersionError, store, uses_git


def files(folder):
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in folder.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(folder).parts
    }


def make_mod(folder):
    (folder / "events").mkdir(parents=True)
    (folder / "events/a.txt").write_bytes(b"country_event = { id = 1 }\r\n")
    (folder / "common").mkdir()
    (folder / "common/b.txt").write_bytes(b"x = 1\n")


def run_story(v, mod):
    """Save, change, save, go back, go forward again: the files follow exactly."""
    first = v.save("first", "the start")
    assert v.info().versions[0].current
    with pytest.raises(VersionError, match="nothing changed"):
        v.save("again")
    one = files(mod)
    (mod / "events/a.txt").write_bytes(b"country_event = { id = 2 }\r\n")
    (mod / "common/c.txt").write_bytes(b"new = yes\n")
    (mod / "common/b.txt").unlink()
    info = v.info()
    assert info.changed == 3 and not info.versions[0].current
    assert {p for _, p in v.compare(first.id)} == {"events/a.txt", "common/c.txt", "common/b.txt"}
    second = v.save("second")
    two = files(mod)
    assert {p for _, p in v.files(second.id)} == {"events/a.txt", "common/b.txt", "common/c.txt"}

    # going back: the files are as in "first" (c.txt removed, b.txt back)
    (mod / "events/a.txt").write_bytes(b"unsaved = yes\n")  # saved automatically first
    v.restore(first.id, "first")
    assert files(mod) == one
    names = [x.name for x in v.info().versions]
    assert any(n.startswith("Automatic: before going to first") for n in names)
    assert v.info().versions[0].current
    # the automatic version holds the unsaved change; second is still there
    auto = next(x for x in v.info().versions if x.auto)
    v.restore(second.id, "second")
    assert files(mod) == two
    v.restore(auto.id, auto.name)
    assert (mod / "events/a.txt").read_bytes() == b"unsaved = yes\n"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_versions(tmp_path):
    mod = tmp_path / "mod"
    make_mod(mod)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "T"]):
        subprocess.run(["git", "-C", str(mod), *args], check=True)
    assert uses_git(mod) and isinstance(store(mod), GitVersions)
    assert "not connected to GitHub" in GitVersions(mod).info().note
    run_story(GitVersions(mod), mod)
    log = subprocess.run(
        ["git", "-C", str(mod), "log", "--format=%s"], capture_output=True, text=True
    )
    assert "Went to the version: first" in log.stdout


def test_copy_versions(tmp_path):
    mod = tmp_path / "mod"
    make_mod(mod)
    assert not uses_git(mod)
    v = store(mod, tmp_path / "versions")
    assert isinstance(v, CopyVersions) and "not connected to GitHub" in v.info().note
    run_story(v, mod)
    # the first zip holds the whole mod, later ones only the changed files; a "went to"
    # version has no zip of its own
    import zipfile

    zips = sorted(v.dir.glob("*.zip"))
    assert len(zips) < len(v.info().versions)
    assert sorted(zipfile.ZipFile(zips[0]).namelist()) == ["common/b.txt", "events/a.txt"]
    assert sorted(zipfile.ZipFile(zips[1]).namelist()) == ["common/c.txt", "events/a.txt"]


def test_api(tmp_path, monkeypatch):
    """The engine refuses while the editor holds unsaved text and reloads after going back."""
    from vic2toolmod.server.app import ApiError, Engine
    from vic2toolmod.workspace import Workspace

    monkeypatch.setattr("vic2toolmod.versions.versions_root", lambda: tmp_path / "versions")
    (tmp_path / "game/events").mkdir(parents=True)
    (tmp_path / "game/events/v.txt").write_text("x = 1\n")
    mod = tmp_path / "mod"
    make_mod(mod)
    engine = Engine(Workspace.open(tmp_path / "game", mod))
    assert engine.versions()["kind"] == "copies"
    with pytest.raises(ApiError, match="name"):
        engine.versions_save({"name": " "})
    first = engine.versions_save({"name": "first"})
    engine.ws.set_text("events/a.txt", "country_event = { id = 9 }\n")
    with pytest.raises(ApiError, match="save or revert"):
        engine.versions_save({"name": "second"})
    engine.ws.revert("events/a.txt")
    (mod / "events/a.txt").write_bytes(b"country_event = { id = 9 }\n")
    assert engine.versions()["changed"] == 1
    files_now = engine.versions_files(first["id"], compare=True)["files"]
    assert files_now == [{"status": "M", "path": "events/a.txt"}]
    engine.versions_restore({"id": first["id"], "name": "first"})
    assert engine.ws.document("events/a.txt").text == "country_event = { id = 1 }\r\n"
    assert [v["auto"] for v in engine.versions()["versions"]][:2] == [False, True]
