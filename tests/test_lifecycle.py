"""Life of the GUI server: exit with the window, one instance, restart on new code."""

import json
import threading
import urllib.request

import pytest

from vic2toolmod.server import lifecycle, make_server
from vic2toolmod.server.lifecycle import Lifetime, code_stamp
from vic2toolmod.workspace import Workspace


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def step(self, seconds, life):
        """Let time pass with the watchdog looking every second."""
        result = False
        for _ in range(int(seconds)):
            self.now += 1
            result = life.should_stop()
            if result:
                break
        return result


def life_and_clock(**kw):
    clock = Clock()
    return Lifetime(grace=5, idle=100, first=300, clock=clock, **kw), clock


def test_stops_after_the_last_tab_said_bye():
    life, clock = life_and_clock()
    life.seen("a")
    life.seen("b")
    life.bye("a")
    assert not clock.step(50, life)  # tab b is still there
    life.seen("b")
    life.bye("b")
    assert not clock.step(4, life)
    assert clock.step(2, life)


def test_a_reload_comes_back_in_time():
    life, clock = life_and_clock()
    life.seen("a")
    life.bye("a")
    clock.step(3, life)
    life.seen()  # the page's files are being loaded: more time
    assert not clock.step(4, life)
    life.seen("a2")  # the new page talks to the API
    assert not clock.step(60, life)


def test_stops_when_the_browser_vanished_or_never_came():
    life, clock = life_and_clock()
    assert not clock.step(299, life)
    assert clock.step(2, life)  # no tab in the first 300 s
    life, clock = life_and_clock()
    life.seen("a")
    assert not clock.step(99, life)
    life.seen("a")  # a slowed-down background tab still asks now and then
    assert not clock.step(99, life)
    assert clock.step(2, life)  # no request for 100 s: the browser is gone


def test_sleep_does_not_count_and_stay_never_stops():
    life, clock = life_and_clock()
    life.seen("a")
    clock.now += 5000  # the computer slept
    assert not life.should_stop()
    assert not clock.step(99, life)
    assert clock.step(2, life)
    life, clock = life_and_clock(auto=False)
    life.seen("a")
    life.bye("a")
    assert not clock.step(1000, life)
    life.stop_now = True
    assert life.should_stop()


def test_code_stamp_follows_the_files(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "notes.md").write_text("ignored\n")
    one = code_stamp(tmp_path)
    (tmp_path / "notes.md").write_text("ignored, changed\n")
    assert code_stamp(tmp_path) == one
    (tmp_path / "a.py").write_text("x = 22\n")
    assert code_stamp(tmp_path) != one
    assert code_stamp() == code_stamp()  # the tool itself: stable between calls


@pytest.fixture
def running(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    game = tmp_path / "game"
    (game / "events").mkdir(parents=True)
    (game / "events/a.txt").write_text("country_event = { id = 1 }\n")
    life = Lifetime(grace=0.2)
    server, token = make_server(Workspace.open(game, None), lifetime=life)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    life.watch(server.shutdown, every=0.05)
    state = {"port": server.server_address[1], "token": token}
    yield state, thread, life
    server.shutdown()
    server.server_close()


def get(state, path, client="", post=False):
    req = urllib.request.Request(
        f"http://127.0.0.1:{state['port']}/api/{path}",
        data=b"{}" if post else None,
        headers={"X-Token": state["token"], "X-Client": client},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_server_stops_when_the_tab_says_bye(running):
    state, thread, _ = running
    info = lifecycle.ping(state)
    assert info is not None and info["stamp"] == code_stamp() and info["stale"] is False
    reply = get(state, "changed", client="tab1")
    assert reply["changed"] == [] and reply["stale"] is False and "memory_mb" in reply
    thread.join(0.6)
    assert thread.is_alive()  # a tab is open
    # sendBeacon cannot set headers: the token and the tab's id are in the address
    url = f"http://127.0.0.1:{state['port']}/api/bye?token={state['token']}&client=tab1"
    urllib.request.urlopen(urllib.request.Request(url, data=b""), timeout=5).read()
    thread.join(5)
    assert not thread.is_alive()
    assert lifecycle.ping(state) is None


def test_quit_and_restart_flags(running):
    state, thread, life = running
    assert get(state, "restart", post=True) == {"ok": True}
    thread.join(5)
    assert not thread.is_alive() and life.restart


def test_ask_to_quit_and_state_file(running):
    state, thread, life = running
    lifecycle.write_state(state["port"], state["token"])
    saved = lifecycle.read_state()
    assert saved is not None and saved["port"] == state["port"]
    assert lifecycle.url_of(saved).endswith(f"/?token={state['token']}")
    assert lifecycle.ask_to_quit(saved, wait=5)
    assert not life.restart
    lifecycle.clear_state(state["port"] + 1)  # another server's port: the file stays
    assert lifecycle.read_state() is not None
    lifecycle.clear_state(state["port"])
    assert lifecycle.read_state() is None
