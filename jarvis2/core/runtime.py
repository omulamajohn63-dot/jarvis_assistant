"""Running the assistant's coroutines from somewhere that already has a loop.

A WSGI server calls a handler from whatever thread and whatever context it
happens to be in. Sometimes there is an event loop running on that thread already
-- starting the dashboard from ``asyncio.run(main())`` does exactly that -- and
then ``asyncio.run`` inside a route raises ``RuntimeError: asyncio.run() cannot
be called from a running event loop``.

The fix is not to avoid having a loop. It is to give the assistant a loop of its
own, in its own thread, and to submit work to it. Then ``handle_input`` can be
called from anywhere: no loop, some loop, another thread, a WSGI worker.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Awaitable
from typing import Any, TypeVar

from jarvis2.logging_utils import get_logger

_log = get_logger("runtime")

T = TypeVar("T")

# Long enough for a drive scan or a document read, short enough that a stuck
# request does not hold the dashboard open for ever.
DEFAULT_TIMEOUT = 300.0


class Runtime:
    """One event loop, on one thread, owned by the assistant."""

    def __init__(self, assistant: Any, timeout: float = DEFAULT_TIMEOUT):
        self.assistant = assistant
        self.timeout = timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    # ------------------------------------------------------------------
    def start(self) -> Runtime:
        """Starts the loop in the background and waits for it to be usable."""
        if self._loop is not None:
            return self

        def spin():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            # Announced only once the loop exists, so a caller that returns from
            # start() can rely on call() working.
            self._ready.set()
            try:
                loop.run_forever()
            finally:
                try:
                    loop.close()
                except Exception:
                    _log.debug("the loop did not close cleanly", exc_info=True)

        self._thread = threading.Thread(
            target=spin, name="jarvis-core", daemon=True,
        )
        self._thread.start()

        if not self._ready.wait(timeout=10):
            raise RuntimeError("the assistant's event loop did not start")
        return self

    @property
    def running(self) -> bool:
        return self._loop is not None and self._loop.is_running()

    # ------------------------------------------------------------------
    def call(self, awaitable: Awaitable[T], timeout: float | None = None) -> T:
        """Runs a coroutine on the assistant's loop and waits for the result.

        Raises if the loop is not running, rather than blocking for ever.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("the assistant's event loop is not running")

        future = asyncio.run_coroutine_threadsafe(awaitable, loop)
        return future.result(self.timeout if timeout is None else timeout)

    def call_soon(self, awaitable: Awaitable[T]) -> asyncio.Future:
        """Schedules a coroutine and returns without waiting for it."""
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("the assistant's event loop is not running")
        return asyncio.run_coroutine_threadsafe(awaitable, loop)

    # ------------------------------------------------------------------
    def stop(self, timeout: float = 5.0) -> None:
        """Closes the assistant and stops the loop.

        The close happens first, while the loop is still running, because
        ``close`` is a coroutine and needs somewhere to run. Closing afterwards
        would either be skipped or leave a resource held, which is how a test
        that stops one assistant leaks a socket into the next.
        """
        self._close_assistant()

        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

        self._loop = None
        self._thread = None
        self._ready.clear()

    def _close_assistant(self) -> None:
        closer = getattr(self.assistant, "close", None)
        if closer is None:
            return

        try:
            pending = closer()
            if inspect.isawaitable(pending):
                self.call(pending)
        except Exception:
            _log.debug("closing the assistant failed", exc_info=True)


class SyncFallback:
    """Used when no Runtime was started, for scripts and tests.

    Only safe where no loop is running, which is why it is the fallback and not
    the default: it says so rather than hanging.
    """

    def __init__(self, assistant: Any):
        self.assistant = assistant

    @property
    def running(self) -> bool:
        return True

    def call(self, awaitable: Awaitable[T], timeout: float | None = None) -> T:
        return asyncio.run(awaitable)  # type: ignore[arg-type]

    def call_soon(self, awaitable: Awaitable[T]):
        loop = self._loop_if_running()
        if loop is not None:
            return asyncio.run_coroutine_threadsafe(awaitable, loop)
        return asyncio.ensure_future(awaitable)

    @staticmethod
    def _loop_if_running():
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    def stop(self, timeout: float = 5.0) -> None:
        closer = getattr(self.assistant, "close", None)
        if closer is not None:
            closer()


def run_in[T](runner, awaitable: Awaitable[T],
              timeout: float | None = None) -> T:
    """Calls a coroutine through whatever runner is available."""
    if runner is None:
        return asyncio.run(awaitable)  # type: ignore[arg-type]
    return runner.call(awaitable, timeout)
