"""The dashboard when something is already running an event loop.

This exists because of a bug the first round of testing missed. Flask's server
can be started from inside asyncio.run -- `python -m jarvis2 --browser` did
exactly that -- and then every request handler that made a loop of its own
failed with "asyncio.run() cannot be called from a running event loop".

The socket tests passed, because they started the server a different way. The
bug was only visible when the server was started the way a person starts it.
"""

import asyncio

import pytest


@pytest.fixture
def app_with_runtime(settings, memory):
    from jarvis2.core.assistant import JarvisAssistant
    from web.app import create_app

    assistant = JarvisAssistant(settings=settings, memory=memory)
    assistant.apply_mute(True)
    app = create_app(assistant, start_runtime=True)
    app.config["TESTING"] = True
    # Deliberately not the `with app.test_client()` form. That one pushes a
    # request context on a context variable, and asyncio.run copies contexts, so
    # its __exit__ pops a context that is no longer there. The failure is in the
    # test client's bookkeeping, not in the handler.
    client = app.test_client()
    yield client, assistant, app
    app.config["runtime"].stop()


class TestRuntime:
    def test_it_runs_a_coroutine(self, settings, memory):
        from jarvis2.core.assistant import JarvisAssistant
        from jarvis2.core.runtime import Runtime

        assistant = JarvisAssistant(settings=settings, memory=memory)
        runtime = Runtime(assistant).start()
        try:
            async def answer():
                return 42

            assert runtime.call(answer()) == 42
            assert runtime.running is True
        finally:
            runtime.stop()

    def test_it_works_from_inside_another_loop(self, settings, memory):
        # The whole point. A loop on this thread must not stop the assistant's
        # loop from being used.
        from jarvis2.core.assistant import JarvisAssistant
        from jarvis2.core.runtime import Runtime

        assistant = JarvisAssistant(settings=settings, memory=memory)
        runtime = Runtime(assistant).start()

        async def from_inside():
            async def answer():
                return "reached"

            return runtime.call(answer())

        try:
            assert asyncio.run(from_inside()) == "reached"
        finally:
            runtime.stop()

    def test_calling_before_it_starts_says_so(self, settings, memory):
        from jarvis2.core.assistant import JarvisAssistant
        from jarvis2.core.runtime import Runtime

        assistant = JarvisAssistant(settings=settings, memory=memory)
        runtime = Runtime(assistant)

        async def nothing():
            return None

        # Says so rather than blocking for ever.
        with pytest.raises(RuntimeError, match="not running"):
            runtime.call(nothing())

    def test_starting_twice_is_harmless(self, settings, memory):
        from jarvis2.core.assistant import JarvisAssistant
        from jarvis2.core.runtime import Runtime

        assistant = JarvisAssistant(settings=settings, memory=memory)
        runtime = Runtime(assistant).start()
        try:
            assert runtime.start() is runtime
        finally:
            runtime.stop()

    def test_stop_closes_the_assistant(self, settings, memory):
        from jarvis2.core.assistant import JarvisAssistant
        from jarvis2.core.runtime import Runtime

        assistant = JarvisAssistant(settings=settings, memory=memory)
        closed = []
        assistant.close = lambda: closed.append(True)

        Runtime(assistant).start().stop()
        assert closed == [True]


class TestHandlersInsideALoop:
    """Every endpoint has to survive being called from inside a loop."""

    def test_chat(self, app_with_runtime):
        client, _assistant, _app = app_with_runtime

        async def ask():
            return client.post("/api/chat", json={"text": "what is the time"})

        response = asyncio.run(ask())
        assert response.status_code == 200
        assert response.get_json()["status"] == "ok"

    def test_chat_with_the_server_started_from_inside_one(self, settings,
                                                           memory):
        # The exact shape of the bug: the app is created and served while a loop
        # is running on this thread.
        from jarvis2.core.assistant import JarvisAssistant
        from web.app import create_app

        assistant = JarvisAssistant(settings=settings, memory=memory)
        app = create_app(assistant)

        async def from_inside_a_loop():
            with app.test_client() as client:
                return client.post("/api/chat", json={"text": "what is the time"})

        response = asyncio.run(from_inside_a_loop())
        try:
            assert response.status_code == 200
            assert response.get_json()["status"] == "ok"
        finally:
            app.config["runtime"].stop()

    def test_confirm(self, app_with_runtime):
        client, _assistant, _app = app_with_runtime

        async def ask():
            client.post("/api/chat", json={"text": "shutdown"})
            return client.post("/api/confirm", json={"id": "1",
                                                     "approved": False})

        response = asyncio.run(ask())
        assert response.status_code == 200
        assert "not do that" in response.get_json()["text"]

    def test_memory(self, app_with_runtime):
        client, _assistant, _app = app_with_runtime

        async def remember():
            return client.post("/api/memory", json={"fact": "my browser is Chrome"})

        assert asyncio.run(remember()).status_code == 200

    def test_history_and_panels(self, app_with_runtime):
        client, _assistant, _app = app_with_runtime

        async def read():
            return [client.get(path) for path in (
                "/api/status", "/api/skills", "/api/settings",
                "/api/history", "/api/memory", "/api/activity",
                "/api/state")]

        for response in asyncio.run(read()):
            assert response.status_code == 200


class TestTheEntryPoint:
    def test_the_browser_path_is_not_a_coroutine(self):
        # Flask's server owns its thread, so serve() must never be awaited, and
        # the entry point that calls it must not be a coroutine either.
        from jarvis2 import __main__ as entry
        from web.app import serve

        assert not asyncio.iscoroutinefunction(serve)
        assert not asyncio.iscoroutinefunction(entry.browser_main)

    def test_the_main_loop_still_handles_the_rest(self):
        from jarvis2 import __main__ as entry

        # The terminal paths are still coroutines; only the server moved out.
        assert asyncio.iscoroutinefunction(entry.main)
        assert asyncio.iscoroutinefunction(entry.run_once)
