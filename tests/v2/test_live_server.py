"""Start the dashboard the way a person starts it, and use it.

The first round of testing started Flask from a script instead of from
`python -m jarvis2 --browser`, so it missed a bug that only appears when the
server is started the way the entry point starts it. This module starts it the
real way and sends real requests at it.

Slow, and worth it: it is the only test that would have caught that.
"""

import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")

# Long enough for the assistant to load and index the applications it can open.
STARTUP_TIMEOUT = 90


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Server:
    """The dashboard, started with the command a person would type."""

    def __init__(self, port: int, home: Path):
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.process = None
        self._home = home
        # Every process this object started, whether or not it is still the
        # current one. A server left running indexes files and holds a port for
        # the rest of the session, which turns one failure into the next ten.
        self._started: list = []
        self._session = None
        # The server writes here rather than into a pipe. A pipe can only be
        # read once it is closed, so reading it to find out what went wrong
        # would mean stopping the server first, and every later test would then
        # fail for that reason instead of its own.
        self._log_path = home / "server.log"

    def start(self) -> "Server":
        # PATH and everything else the child needs is kept: replacing the whole
        # environment would strip them before it reached the first line of
        # asyncio. Only the per-user folders are redirected, because the suite
        # points them at a temporary directory that belongs to whichever test
        # happens to be running, and the server outlives every one of them.
        environment = dict(os.environ)
        environment["APPDATA"] = str(self._home / "AppData")
        environment["LOCALAPPDATA"] = str(self._home / "AppData")
        # Werkzeug logs one line per request. Unbuffered, so the log is complete
        # at the moment something goes wrong rather than 4 KB later.
        environment["PYTHONUNBUFFERED"] = "1"

        with self._log_path.open("w", encoding="utf-8") as log:
            self.process = subprocess.Popen(
                [PYTHON, "-m", "jarvis2", "--browser", "--port", str(self.port)],
                cwd=str(ROOT),
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT)
        self._started.append(self.process)
        self.wait_until_ready()
        return self

    def wait_until_ready(self) -> None:
        deadline = time.time() + STARTUP_TIMEOUT
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(
                    "the server stopped:\n" + self.server_log()
                )
            # A fresh client each time round: the readiness probe is the one
            # request made before anything is known to be listening, and it must
            # not be the one that fails on a stale pooled connection.
            self._session = None
            try:
                self._send("GET", "/api/state", timeout=2, report=False)
                return
            except Exception:
                time.sleep(0.5)
        raise AssertionError("the server did not become ready")

    def _client(self):
        """One pooled HTTP client for the whole module.

        requests is used rather than urllib or a hand-rolled socket because it
        does the boring part properly: it pools connections the way a browser
        does and it retries a connection that was dropped by the far end. Both
        of those were being got wrong by hand, and the symptom was a test that
        timed out against a server whose own log showed it had answered.
        """
        import requests
        from requests.adapters import HTTPAdapter

        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=1, pool_maxsize=4, max_retries=2)
        session.mount("http://", adapter)
        return session

    def _send(self, method: str, path: str, body=None, timeout: float = 30,
              report: bool = True):
        """One request.

        ``report`` attaches the server's own log to a failure. Which request it
        logged and which it did not is the whole diagnosis, and without it this
        test can only say "it timed out". It is off for the readiness probe,
        which is expected to fail and would otherwise spend half a minute on
        every attempt.
        """
        if self._session is None:
            self._session = self._client()

        try:
            response = self._session.request(
                method, self.base + path, json=body, timeout=timeout)
            return response.status_code, response.content
        except Exception as error:
            if not report:
                raise
            raise AssertionError(
                f"{method} {path} failed: {type(error).__name__}: {error}\n"
                f"--- what the server logged ---\n{self.server_log()}"
            ) from error

    def server_log(self) -> str:
        """Whatever the server has written so far. Reads without stopping it."""
        try:
            return self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            return f"(the log could not be read: {error})"

    def get(self, path: str):
        status, raw = self._send("GET", path)
        return status, json.loads(raw)

    def post(self, path: str, payload):
        status, raw = self._send("POST", path, body=payload)
        return status, json.loads(raw)

    def output(self) -> str:
        return ""

    def stop(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        for process in list(self._started):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        self._started.clear()
        self.process = None


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """One real server for the module, started the real way."""
    home = tmp_path_factory.mktemp("server-home")
    server = Server(free_port(), home).start()
    try:
        yield server
    finally:
        server.stop()


class TestStartedTheWayAPersonStartsIt:
    def test_it_becomes_ready(self, live):
        status, data = live.get("/api/state")
        assert status == 200
        assert data["name"]

    def test_a_typed_command_is_answered(self, live):
        # This is the request that failed. The server was started from inside
        # asyncio.run, so every handler that made a loop of its own raised
        # "asyncio.run() cannot be called from a running event loop".
        status, data = live.post("/api/chat", {"text": "what is the time"})
        assert status == 200
        assert data["status"] == "ok"
        assert data["text"]

    def test_several_commands_in_a_row(self, live):
        # Once is not enough: a loop left running would fail every time, and a
        # loop left behind by the first request would fail the second.
        for question in ("what is the date", "tell me a joke", "hello",
                         "what can you do"):
            status, data = live.post("/api/chat", {"text": question})
            assert status == 200, question
            assert data["text"], question

    def test_the_page_and_its_assets_load(self, live):
        for path in ("/", "/styles.css", "/app.js", "/static/app.js",
                     "/static/styles.css"):
            status, _body = live._send("GET", path)
            assert status == 200, path

    def test_a_risky_command_asks_rather_than_acting(self, live):
        status, data = live.post("/api/chat", {"text": "shutdown"})
        assert status == 200
        assert data["status"] == "needs_confirmation"
        assert data["confirmation"]["risk"] == "high"

        _status, answered = live.post("/api/confirm", {
            "id": data["confirmation"]["id"], "approved": False,
        })
        assert "not do that" in answered["text"]

    def test_a_question_about_power_asks_nothing(self, live):
        _status, data = live.post(
            "/api/chat", {"text": "how do i restart windows safely"}
        )
        assert data["confirmation"] is None

    def test_every_panel_answers(self, live):
        for path in ("/api/status", "/api/skills", "/api/settings",
                     "/api/history", "/api/memory", "/api/activity"):
            status, data = live.get(path)
            assert status == 200, path
            assert isinstance(data, dict), path

    def test_memory_round_trips(self, live):
        live.post("/api/memory", {"fact": "my browser is Chrome"})
        _status, data = live.get("/api/memory")
        assert any(fact["key"] == "browser" for fact in data["facts"])
        live.post("/api/chat", {"text": "clear my memory"})

    def test_a_setting_round_trips(self, live):
        _status, before = live.get("/api/settings")
        _status, after = live.post("/api/settings", {
            "voiceEnabled": not before["voiceEnabled"],
        })
        assert after["voiceEnabled"] is not before["voiceEnabled"]
        live.post("/api/settings", {"voiceEnabled": before["voiceEnabled"]})

    def test_history_accumulates(self, live):
        live.post("/api/chat", {"text": "what is the time"})
        _status, data = live.get("/api/history")
        assert data["turns"]

    def test_the_server_logs_no_traceback(self, live):
        # The bug printed a full traceback to the console. Nothing in a normal
        # exchange should.
        live.post("/api/chat", {"text": "what is the time"})
        time.sleep(0.5)
        # Non-blocking peek at what has been written so far.
        output = live.server_log()
        live.process.terminate()
        live.process.wait(timeout=10)
        live.process = None
        assert "Traceback" not in output, output[-1500:]
