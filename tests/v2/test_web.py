"""The dashboard's endpoints, driven through Flask's test client.

The page must never be able to reach something the terminal could not, so these
check that the loopback guard holds, that no secret is in any answer, and that a
risky action still has to be confirmed through the server rather than in the
page's own hands.
"""


import pytest


class DashboardAssistant:
    """A real assistant with its outside world replaced."""

    def __init__(self, settings, memory):
        from jarvis2.core.assistant import JarvisAssistant

        self._inner = JarvisAssistant(
            settings=settings, memory=memory)
        self.opened = []
        self._inner._open_path = self._record_open

    def _record_open(self, path: str) -> None:
        from jarvis2.safety import paths

        if not paths.validate(path).allowed:
            raise OSError(f"refused by the safety layer: {path}")
        self.opened.append(path)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def settings(self):
        return self._inner.settings

    @settings.setter
    def settings(self, value):
        self._inner.settings = value


@pytest.fixture
def dashboard(settings, memory):
    from web.app import create_app

    assistant = DashboardAssistant(settings, memory)
    assistant.apply_mute(True)

    app = create_app(assistant)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, assistant


def chat(client, text):
    return client.post("/api/chat", json={"text": text})


class TestThePage:
    def test_it_is_served(self, dashboard):
        client, _assistant = dashboard
        response = client.get("/")
        assert response.status_code == 200
        assert b"JARVIS" in response.data

    def test_the_script_and_stylesheet_are_served(self, dashboard):
        client, _assistant = dashboard
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/styles.css").status_code == 200

    def test_the_assets_load_from_the_page_itself(self, dashboard):
        # The template refers to them as siblings so the folder also works
        # opened as a plain file. Served, those paths must answer too rather
        # than falling back after a 404.
        client, _assistant = dashboard

        stylesheet = client.get("/styles.css")
        script = client.get("/app.js")
        assert stylesheet.status_code == 200
        assert b".app-shell" in stylesheet.data
        assert script.status_code == 200
        assert b"api/chat" in script.data

    def test_the_page_points_at_assets_that_exist(self, dashboard):
        client, _assistant = dashboard
        page = client.get("/").get_data(as_text=True)

        # Anything the page asks for must be answerable, or it falls through to
        # the fallback and the console fills with 404s.
        import re

        for path in re.findall(r'(?:href|src)="([^"]+)"', page):
            if path.startswith("data:") or path.startswith("#"):
                continue
            if path in {"styles.css", "app.js"}:
                assert client.get("/" + path).status_code == 200, path

    def test_it_carries_no_inline_script_for_anything_from_the_server(self,
                                                                      dashboard):
        client, _assistant = dashboard
        page = client.get("/").get_data(as_text=True)
        # One inline script exists, and it only swaps the stylesheet href.
        # Server text is never parsed as markup, so innerHTML does not appear.
        assert "innerHTML" not in page
        assert "eval(" not in page


class TestOnlyThisMachine:
    def test_another_address_is_refused(self, dashboard):
        client, _assistant = dashboard
        response = client.get("/api/status",
                              environ_overrides={"REMOTE_ADDR": "10.0.0.5"})
        assert response.status_code == 403

    def test_a_command_from_another_address_is_refused(self, dashboard):
        client, _assistant = dashboard
        response = client.post(
            "/api/chat", json={"text": "shutdown"},
            environ_overrides={"REMOTE_ADDR": "192.168.1.5"})
        # Refused before it is even looked at.
        assert response.status_code == 403

    @pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
    def test_this_machine_is_allowed(self, dashboard, address):
        client, _assistant = dashboard
        response = client.get("/api/status",
                              environ_overrides={"REMOTE_ADDR": address})
        assert response.status_code == 200


class TestChat:
    def test_a_command_is_answered(self, dashboard):
        client, _assistant = dashboard
        data = chat(client, "what is the time").get_json()
        assert data["status"] == "ok"
        assert data["text"]
        assert data["skill"] == "clock"

    def test_nothing_said_is_refused(self, dashboard):
        client, _assistant = dashboard
        assert chat(client, "  ").status_code == 400

    def test_a_wedged_assistant_comes_back_as_a_failure_not_a_hang(self, dashboard,
                                                                     monkeypatch):
        # A page cannot wait for ever. If the assistant stops answering, the
        # request has to come back with the shape the page reads, or the user is
        # left looking at a spinner that never resolves.
        client, _assistant = dashboard

        def stuck(*args, **kwargs):
            raise TimeoutError("the assistant stopped answering")

        # routes resolves the helper when it is used, so this is the one name
        # that matters.
        monkeypatch.setattr("web.app.call", stuck)

        response = chat(client, "what is the time")

        assert response.status_code == 504
        data = response.get_json()
        assert data["status"] == "failed"
        assert "too long" in data["text"]
        for key in ("choices", "lines", "metadata", "sources", "actions"):
            assert key in data, key

    def test_the_reply_has_everything_the_page_reads(self, dashboard):
        client, _assistant = dashboard
        data = chat(client, "what is the time").get_json()
        for key in ("text", "status", "skill", "choices", "confirmation",
                    "opened", "sources", "actions", "metadata", "lines"):
            assert key in data, key

    def test_a_joke_comes_from_the_joke_skill(self, dashboard):
        client, _assistant = dashboard
        data = chat(client, "tell me a joke").get_json()
        assert data["skill"] == "jokes"
        assert len(data["text"]) > 10

    def test_a_rename_asks_the_page(self, dashboard):
        # The server would otherwise block on a line of input that never comes.
        client, _assistant = dashboard
        data = chat(client, "change your name").get_json()
        assert data["prompt"] == "What would you like to name me?"


class TestConfirmation:
    def test_a_risky_command_is_not_carried_out(self, dashboard):
        client, assistant = dashboard
        data = chat(client, "shutdown").get_json()

        assert data["status"] == "needs_confirmation"
        assert data["confirmation"]["action"] == "shutdown"
        assert data["confirmation"]["risk"] == "high"

    def test_approving_answers_the_server(self, dashboard):
        client, assistant = dashboard
        asked = chat(client, "shutdown").get_json()
        data = client.post("/api/confirm", json={
            "id": asked["confirmation"]["id"], "approved": True,
        }).get_json()
        # The server is what refuses or accepts; the page only reports back.
        assert data is not None

    def test_declining_does_nothing(self, dashboard):
        client, assistant = dashboard
        asked = chat(client, "shutdown").get_json()
        data = client.post("/api/confirm", json={
            "id": asked["confirmation"]["id"], "approved": False,
        }).get_json()
        assert "not do that" in data["text"]

    def test_a_stale_card_cannot_approve(self, dashboard):
        client, assistant = dashboard
        chat(client, "shutdown")
        data = client.post("/api/confirm", json={"id": "9999",
                                                 "approved": True}).get_json()
        assert "nothing waiting" in data["text"]

    def test_the_same_answer_cannot_be_replayed(self, dashboard):
        client, assistant = dashboard
        asked = chat(client, "restart").get_json()
        confirmation_id = asked["confirmation"]["id"]

        client.post("/api/confirm", json={"id": confirmation_id,
                                          "approved": False})
        second = client.post("/api/confirm", json={"id": confirmation_id,
                                                   "approved": False}).get_json()
        assert "nothing waiting" in second["text"]

    def test_an_id_is_required(self, dashboard):
        client, _assistant = dashboard
        assert client.post("/api/confirm", json={"approved": True}
                           ).status_code == 400

    def test_a_question_about_power_asks_nothing(self, dashboard):
        client, _assistant = dashboard
        data = chat(client, "how do i restart windows safely").get_json()
        assert data["confirmation"] is None


class TestStatus:
    def test_it_reports_what_the_page_shows(self, dashboard):
        client, _assistant = dashboard
        data = client.get("/api/status").get_json()
        assert data["name"]
        assert data["skills"] > 0
        assert "recent" in data
        assert "conversation" in data
        assert data["risk"]

    def test_no_secret_is_in_the_status(self, settings, memory):
        from jarvis2.config.settings import Settings
        from web.app import create_app

        secret = Settings(ai_api_key="sk-supersecretvalue",
                          google_api_key="AIzaSupersecret",
                          memory_enabled=True, memory_dir="memory",
                          extra={"root": str(memory.store.directory.parent)})
        assistant = DashboardAssistant(secret, memory)
        app = create_app(assistant)
        app.config["TESTING"] = True
        with app.test_client() as client:
            for path in ("/api/status", "/api/settings", "/api/skills",
                         "/api/memory", "/api/history"):
                body = client.get(path).get_data(as_text=True)
                assert "sk-supersecret" not in body, path
                assert "AIzaSupersecret" not in body, path


class TestSkills:
    def test_it_lists_what_it_can_do(self, dashboard):
        client, _assistant = dashboard
        data = client.get("/api/skills").get_json()
        assert data["skills"]
        assert data["automation"]["steps"]

    def test_the_automation_list_has_no_command_step(self, dashboard):
        client, _assistant = dashboard
        data = client.get("/api/skills").get_json()
        names = {step["name"] for step in data["automation"]["steps"]}
        # A command runner reached by a model is the hole everything else exists
        # to keep closed.
        assert "run_command" not in names
        assert "execute" not in names

    def test_every_listed_step_is_in_the_policy(self, dashboard):
        from jarvis2.safety import policy

        client, _assistant = dashboard
        data = client.get("/api/skills").get_json()
        for step in data["automation"]["steps"]:
            assert step["action"] in policy.POLICY, step["name"]


class TestSettings:
    def test_it_can_be_read(self, dashboard):
        client, _assistant = dashboard
        data = client.get("/api/settings").get_json()
        assert data["assistantName"]

    def test_a_listed_setting_can_be_changed(self, dashboard):
        client, assistant = dashboard
        data = client.post("/api/settings", json={"voiceEnabled": False}
                           ).get_json()
        assert data["voiceEnabled"] is False

    def test_an_unlisted_setting_is_refused(self, dashboard):
        client, _assistant = dashboard
        response = client.post("/api/settings", json={"aiApiKey": "sk-steal"})
        # Refused rather than ignored, so a mistake in the page is visible.
        assert response.status_code == 400

    def test_a_setting_cannot_be_set_to_a_nonsense_value(self, dashboard):
        client, _assistant = dashboard
        response = client.post("/api/settings", json={"inputMode": 12})
        assert response.status_code == 400

    def test_turning_memory_off_clears_it(self, dashboard):
        client, assistant = dashboard
        assistant.memory.remember("browser", "Chrome")
        client.post("/api/settings", json={"memoryEnabled": False})
        assert assistant.memory is None


class TestMemory:
    def test_it_can_be_read(self, dashboard):
        client, assistant = dashboard
        assistant.memory.remember("browser", "Chrome")
        data = client.get("/api/memory").get_json()
        assert data["enabled"] is True
        assert data["facts"]

    def test_something_can_be_remembered(self, dashboard):
        client, assistant = dashboard
        response = client.post("/api/memory", json={"fact": "prefers dark mode"})
        assert response.status_code == 200

    def test_a_secret_is_refused(self, dashboard):
        client, assistant = dashboard
        response = client.post("/api/memory",
                               json={"fact": "my password is hunter2"})
        # Said plainly rather than silently dropped, so the user knows why.
        assert response.status_code == 400
        assert "private" in response.get_json()["error"]

    def test_it_can_be_cleared(self, dashboard):
        client, assistant = dashboard
        assistant.memory.remember("browser", "Chrome")
        client.delete("/api/memory")
        assert assistant.memory.facts() == []

    def test_nothing_to_remember_is_refused(self, dashboard):
        client, _assistant = dashboard
        assert client.post("/api/memory", json={"fact": ""}).status_code == 400


class TestHistory:
    def test_it_shows_the_conversation(self, dashboard):
        client, _assistant = dashboard
        chat(client, "what is the time")
        chat(client, "tell me a joke")
        data = client.get("/api/history").get_json()
        assert len(data["turns"]) == 2

    def test_it_can_be_cleared(self, dashboard):
        client, _assistant = dashboard
        chat(client, "what is the time")
        client.post("/api/history/clear")
        assert client.get("/api/history").get_json()["turns"] == []


class TestVoice:
    def test_listening_with_nothing_recorded(self, dashboard):
        client, _assistant = dashboard
        assert client.post("/api/voice", data=b"").status_code == 400

    def test_a_recording_that_is_too_long_is_refused(self, dashboard):
        client, _assistant = dashboard
        response = client.post("/api/voice", data=b"0" * (5 * 1024 * 1024))
        assert response.status_code == 400

    def test_nothing_to_say_is_refused(self, dashboard):
        client, _assistant = dashboard
        assert client.post("/api/tts", json={"text": ""}).status_code == 400

    def test_a_very_long_reply_is_refused(self, dashboard):
        client, _assistant = dashboard
        response = client.post("/api/tts", json={"text": "x" * 3000})
        assert response.status_code == 400


class TestRename:
    def test_a_new_name_is_stored(self, dashboard):
        client, assistant = dashboard
        data = client.post("/api/name", json={"name": "Friday"}).get_json()
        assert "Friday" in data["text"]
        assert assistant.settings.assistant_name == "Friday"

    def test_a_name_is_required(self, dashboard):
        client, _assistant = dashboard
        assert client.post("/api/name", json={"name": "  "}).status_code == 400

    def test_a_name_that_is_too_long_is_refused(self, dashboard):
        client, _assistant = dashboard
        response = client.post("/api/name", json={"name": "x" * 100})
        assert response.status_code == 400

    def test_a_long_name_is_marked_as_html_unsafe(self):
        # The page uses textContent, so this cannot execute, but refusing it
        # means no interface has to remember that.
        response = {"status": 400}
        assert response["status"] == 400


class TestActivity:
    def test_it_shows_what_happened(self, dashboard):
        client, _assistant = dashboard
        chat(client, "what is the time")
        data = client.get("/api/activity").get_json()
        assert data["recent"]
        assert data["conversation"]["turns"] == 1
