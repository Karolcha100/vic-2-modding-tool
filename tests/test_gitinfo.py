import subprocess

from vic2toolmod import gitinfo


def test_status_and_diff(tmp_path):
    assert not gitinfo.status(tmp_path).repo
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        check=True,
    )
    (tmp_path / "a.txt").write_text("hello\n")
    st = gitinfo.status(tmp_path)
    assert st.repo and st.branch == "main" and st.changed == (("??", "a.txt"),)
    assert gitinfo.diff(tmp_path, "a.txt") == "+hello\n"
