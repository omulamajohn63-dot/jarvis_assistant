"""The browser interface.

Same assistant, with a browser for a face. Every endpoint here goes through
JarvisAssistant.handle_input, so a command behaves the same as it does in a
terminal, and none of the presentation reaches past it.

Bound to loopback and refusing anything that did not come from this computer, so
the Wi-Fi and the internet cannot reach it.

The assistant's coroutines run on a loop of its own, in its own thread, so a
handler works no matter what the calling thread happens to be doing. See
jarvis2/core/runtime.py for why that matters.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from flask import Flask, request

from jarvis2.logging_utils import get_logger

_log = get_logger("web")

# Where the dashboard's files live, whether this is run as a module or directly.
HERE = Path(__file__).resolve().parent

# Refused in _only_this_machine. The server binds to loopback as well; this
# guards against a proxy on this machine forwarding requests in from elsewhere.
LOCAL_ADDRESSES = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def create_app(assistant=None, runtime=None, start_runtime: bool = True) -> Flask:
    """Builds the dashboard around one assistant instance.

    ``start_runtime`` is turned off by tests that drive the app through their own
    loop, because two loops for one assistant would mean two sets of state.
    """
    from jarvis2.core.runtime import Runtime, SyncFallback

    app = Flask(
        __name__,
        static_folder=str(HERE / "static"),
        static_url_path="/static",
        template_folder=str(HERE / "templates"),
    )
    app.config["assistant"] = assistant
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

    if runtime is None and assistant is not None:
        runtime = Runtime(assistant).start() if start_runtime \
            else SyncFallback(assistant)
    app.config["runtime"] = runtime

    from web.api import routes

    routes.register(app)
    return app


def get_assistant() -> object:
    """The assistant this request belongs to."""
    from flask import current_app

    assistant = current_app.config.get("assistant")
    if assistant is None:
        raise RuntimeError("the dashboard has no assistant attached")
    return assistant


def get_runtime():
    """The runner the handlers use to reach the assistant."""
    from flask import current_app

    return current_app.config.get("runtime")


# How long a page will wait for the assistant before giving up. The assistant
# itself allows longer, because a full scan of every drive really can take
# minutes, but a browser that waits that long has stopped being usable: the
# request comes back as a failure instead, which is honest, rather than the page
# sitting on a spinner with nothing to show.
REQUEST_TIMEOUT = 60.0


def call(awaitable, timeout: float | None = None):
    """Runs a coroutine on the assistant's own loop.

    This is the only way a handler should touch the assistant. Calling
    asyncio.run here instead would break as soon as the server is started from
    inside a loop, which is exactly what `python -m jarvis2 --browser` does.
    """
    from jarvis2.core.runtime import run_in

    return run_in(get_runtime(), awaitable,
                  REQUEST_TIMEOUT if timeout is None else timeout)


def _client_ip() -> str:
    return request.remote_addr or ""


def serve(host: str = None, port: int = None, assistant=None,
          open_browser: bool = True) -> int:
    """Starts the dashboard.

    Replies are rendered to audio for the page to play, so the assistant is muted
    here: speaking them as well would double every reply up.

    Deliberately not a coroutine and deliberately not called from inside one.
    Flask's server owns this thread, and leaving a loop running on it is what
    made every request fail.
    """
    if assistant is None:
        import asyncio

        from jarvis2.core.assistant import build

        assistant = asyncio.run(build())

    settings = assistant.settings
    host = host or settings.host
    port = port or settings.port

    assistant.apply_mute(True)
    app = create_app(assistant)

    url = f"http://{host}:{port}"
    print(f"{settings.assistant_name} is listening on {url}")
    print("Press Ctrl+C to close it.")

    if open_browser:
        import webbrowser

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        # Single threaded, because the numbered results list and the command
        # answering it share one session's state.
        app.run(host=host, port=port, debug=False, threaded=False,
                use_reloader=False)
    except OSError as error:
        print(f"Could not start on port {port}: {error}")
        print("Close whatever is using that port, or set PORT in .env.")
        return 1
    except KeyboardInterrupt:
        print()
        print(f"{settings.assistant_name} is offline. Goodbye.")
    finally:
        runtime = app.config.get("runtime")
        if runtime is not None:
            runtime.stop()
    return 0


def main() -> int:
    """Entry point for `python -m web.app` and the reloader."""
    return serve()


if __name__ == "__main__":
    sys.exit(main())
