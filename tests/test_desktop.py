from vic2toolmod.desktop import desktop_entry, install_desktop


def test_install_desktop(tmp_path):
    path = install_desktop(tmp_path)
    text = path.read_text()
    assert text.startswith("[Desktop Entry]") and "-m vic2toolmod gui" in text
    assert text == desktop_entry()
