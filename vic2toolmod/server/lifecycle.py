"""Life of the GUI server: one instance, exit with the browser window, restart on new code.

* **Exit with the window.** Every browser tab of the GUI has a client id (header
  ``X-Client``) and says ``bye`` when it is closed. `Lifetime` stops the server
  a few seconds after the last tab said bye (a reload says bye and comes right
  back), and also when no request at all arrived for a few minutes (the browser
  was killed) or no tab ever connected. ``gui --stay`` turns this off
  (``auto=False``: the server then stops only when told to).
* **One instance.** The server started by a plain ``vic2toolmod gui`` writes its
  port and token to ``gui-server.json`` next to the settings file. The next
  plain start finds it: with the same code on disk it only opens a browser tab
  on the running server; with newer code it tells the old server to quit and
  takes its place.
* **New code.** `code_stamp` is a fingerprint of the tool's files (Python,
  schema data, built frontend). The GUI learns from ``/api/changed`` that the
  files changed since the server started and offers a restart; the restarted
  server keeps its port and token, so the page only has to reload.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vic2toolmod.config import config_path

PACKAGE = Path(__file__).resolve().parent.parent
_CODE_SUFFIXES = (".py", ".yaml", ".js", ".css", ".html", ".txt")
RESUME_ENV = "VIC2TOOLMOD_RESUME"
"""Environment variable with the state a restarted server takes over (JSON)."""


def code_stamp(root: Path = PACKAGE) -> str:
    """Fingerprint of the tool's files: changes when any of them is edited or rebuilt."""
    digest = hashlib.sha1(usedforsecurity=False)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            if name.endswith(_CODE_SUFFIXES):
                path = os.path.join(dirpath, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                digest.update(f"{path}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return digest.hexdigest()[:16]


class Lifetime:
    """Decides when the server has nothing left to live for.

    Args:
        grace: Seconds to wait after the last tab said bye (a reload returns sooner).
        idle: Seconds without any request after which the browser is taken for gone
            (background tabs are slowed down by browsers to one request a minute).
        first: Seconds to wait for the first tab.
        auto: Stop on its own; ``False``: only on ``stop_now`` (``gui --stay``).
        clock: Time source (seconds, never goes back).
    """

    def __init__(
        self,
        grace: float = 6.0,
        idle: float = 180.0,
        first: float = 900.0,
        auto: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.grace, self.idle, self.first, self.auto = grace, idle, first, auto
        self._clock = clock
        self._lock = threading.Lock()
        self._clients: set[str] = set()
        self._had_client = False
        self._last = clock()
        self._closing: float | None = None
        self._tick = clock()
        self.stop_now = False
        """Set by ``/api/quit`` and ``/api/restart``: stop at the next look."""
        self.restart = False
        """Start again with the same port and token after stopping."""

    def seen(self, client: str = "") -> None:
        """A request arrived (``client``: the tab's id, empty for images and static files)."""
        with self._lock:
            now = self._clock()
            self._last = now
            if client:
                self._clients.add(client)
                self._had_client = True
                self._closing = None
            elif self._closing is not None:
                self._closing = now + self.grace  # the page of a reload is still loading

    def bye(self, client: str) -> None:
        """A tab was closed (or reloaded)."""
        with self._lock:
            self._clients.discard(client)
            if not self._clients:
                self._closing = self._clock() + self.grace

    def should_stop(self) -> bool:
        """Call every second or two: is it time to stop?"""
        with self._lock:
            now = self._clock()
            # The computer slept (or the process was stopped): that time does not count.
            gap = now - self._tick
            self._tick = now
            if gap > 30:
                self._last += gap
                if self._closing is not None:
                    self._closing += gap
                return False
            if self.stop_now:
                return True
            if not self.auto:
                return False
            if self._closing is not None and now >= self._closing:
                return True
            if self._had_client:
                return now - self._last > self.idle
            return now - self._last > self.first

    def watch(self, stop: Callable[[], None], every: float = 1.5) -> threading.Thread:
        """Start a thread that calls ``stop`` once when the time has come."""

        def loop() -> None:
            while not self.should_stop():
                time.sleep(every)
            stop()

        thread = threading.Thread(target=loop, name="lifetime", daemon=True)
        thread.start()
        return thread


# -- the registered instance ---------------------------------------------------------
def state_path() -> Path:
    """Where the running server of a plain ``vic2toolmod gui`` is written down."""
    return config_path().parent / "gui-server.json"


def write_state(port: int, token: str) -> None:
    """Record this process as the running GUI server."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"port": port, "token": token, "pid": os.getpid()}))
    tmp.chmod(0o600)  # the token lets a program use the API
    tmp.replace(path)


def read_state() -> dict[str, Any] | None:
    """The recorded server, if the file is there and readable."""
    try:
        data = json.loads(state_path().read_text())
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("port"), int) and data.get("token"):
        return data
    return None


def clear_state(port: int) -> None:
    """Forget the recorded server if it is the one on ``port``."""
    state = read_state()
    if state and state["port"] == port:
        state_path().unlink(missing_ok=True)


def url_of(state: dict[str, Any]) -> str:
    """Address of the GUI of a recorded server."""
    return f"http://127.0.0.1:{state['port']}/?token={state['token']}"


def _request(state: dict[str, Any], path: str, post: bool = False) -> dict[str, Any] | None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{state['port']}/api/{path}",
        data=b"{}" if post else None,
        headers={"X-Token": str(state["token"]), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310 - localhost
            data = json.loads(response.read())
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return data if isinstance(data, dict) else None


def ping(state: dict[str, Any]) -> dict[str, Any] | None:
    """``{"stamp": …, "pid": …}`` of the recorded server, ``None`` when it does not answer."""
    return _request(state, "ping")


def ask_to_quit(state: dict[str, Any], wait: float = 8.0) -> bool:
    """Tell a recorded server to stop and wait until it no longer answers."""
    _request(state, "quit", post=True)
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if ping(state) is None:
            return True
        time.sleep(0.2)
    return False
