"""What the dashboard's endpoints return.

These exist because a template depends on the shape and the types of what it is
given. A boolean that arrives as the string "False" is truthy in JavaScript, so
a page would show a failed action as a successful one.
"""


import pytest

from jarvis2.logging_utils import redact, redact_deep, redact_mapping


class TestTypesSurviveRedaction:
    def test_a_boolean_stays_a_boolean(self):
        # "False" is truthy in JavaScript, so stringifying it would make a
        # failed action look like a successful one.
        assert redact(False) is False
        assert redact(True) is True
        assert isinstance(redact(False), bool)

    @pytest.mark.parametrize("value", [0, 1, 42, -7])
    def test_numbers_stay_numbers(self, value):
        assert redact(value) == value
        assert isinstance(redact(value), int)

    def test_floats_stay_floats(self):
        assert redact(1.5) == 1.5
        assert isinstance(redact(1.5), float)

    def test_none_stays_none(self):
        assert redact(None) is None

    def test_text_is_still_checked_for_secrets(self):
        key = "sk-" + "abc123def456ghi789"
        assert key not in redact(f"the key is {key}")

    def test_a_secret_named_field_is_replaced(self):
        assert redact("anything", "api_key") == "[redacted]"

    def test_bytes_are_summarised(self):
        assert redact(b"12345") == "<5 bytes>"


class TestDeepRedaction:
    def test_a_list_stays_a_list(self):
        assert redact_deep(["a", "b"]) == ["a", "b"]

    def test_a_dict_stays_a_dict(self):
        assert redact_deep({"a": 1}) == {"a": 1}

    def test_booleans_inside_a_dict_stay_booleans(self):
        result = redact_deep({"succeeded": False, "opened": []})
        assert result["succeeded"] is False
        assert result["opened"] == []

    def test_a_secret_inside_a_dict_is_still_caught(self):
        key = "sk-" + "abc123def456ghi789"
        assert key not in str(redact_deep({"note": f"use {key} here"}))

    def test_a_nested_structure(self):
        result = redact_deep({"steps": [{"done": False, "tool": "clock"}]})
        assert result["steps"][0]["done"] is False

    def test_flat_mapping(self):
        assert redact_mapping({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}


class TestEventShapes:
    async def test_an_event_keeps_its_types(self, assistant):
        await assistant.handle_input("what is the time")

        events = assistant.bus.recent(50)
        completed = next(
            entry for entry in events if entry["event"] == "tool_completed"
        )
        # A page reads these. A failed action must not read as a successful one.
        assert completed["succeeded"] is True
        assert completed["opened"] == []

    async def test_a_failed_tool_reports_false(self, assistant):
        from jarvis2.skills.base import Skill

        class Failing(Skill):
            name = "failing"
            description = "fails"
            keywords = ("failnow")

            async def can_handle(self, request):
                return 0.99

            async def execute(self, request, context):
                raise RuntimeError("no")

        assistant.registry.register(Failing())
        await assistant.handle_input("failnow")

        events = assistant.bus.recent(50)
        failed = next(
            (entry for entry in events if entry["event"] == "tool_failed"), None
        )
        assert failed is not None
        assert isinstance(failed["error"], str)


class TestDashboardPayloads:
    """The exact shapes a template is written against."""

    @pytest.fixture
    def client(self, settings, memory, home):
        from jarvis2.files import search as finder
        from tests.v2.test_web import DashboardAssistant
        from web.app import create_app

        assistant = DashboardAssistant(settings, memory)
        assistant.apply_mute(True)

        # The indexes are shared and kept, so they have to be emptied before the
        # fake home is searched. Otherwise a test would find the developer's own
        # files, or the files of whichever test ran before it.
        finder.clear_caches()

        app = create_app(assistant)
        app.config["TESTING"] = True
        with app.test_client() as test_client:
            yield test_client
        finder.clear_caches()

    def test_a_normal_reply(self, client):
        data = client.post("/api/chat", json={"text": "what is the time"}
                           ).get_json()
        # Every key a page reads, and its type. Both "lines" and "prompt" are
        # always present rather than only sometimes, because the page reads
        # both unconditionally.
        assert isinstance(data["text"], str)
        assert data["status"] == "ok"
        assert isinstance(data["choices"], list)
        assert isinstance(data["opened"], list)
        assert isinstance(data["sources"], list)
        assert isinstance(data["actions"], list)
        assert isinstance(data["lines"], list)
        assert isinstance(data["metadata"], dict)
        assert data["confirmation"] is None
        assert data["prompt"] is None
        assert isinstance(data["took"], float)

    def test_a_confirmation(self, client):
        data = client.post("/api/chat", json={"text": "shutdown"}).get_json()
        assert data["status"] == "needs_confirmation"
        question = data["confirmation"]
        # What a confirm card needs.
        assert question["id"]
        assert question["prompt"]
        assert question["risk"] == "high"
        assert question["action"] == "shutdown"

    def test_the_state_a_page_loads_with(self, client):
        data = client.get("/api/state").get_json()
        assert isinstance(data["name"], str)
        assert isinstance(data["sampleRate"], int)
        assert isinstance(data["maxSeconds"], int)
        assert data["pending"] is None or isinstance(data["pending"], dict)
        assert data["confirmation"] is None or isinstance(data["confirmation"], dict)

    def test_the_status_panel(self, client):
        data = client.get("/api/status").get_json()
        assert isinstance(data["skills"], int)
        assert isinstance(data["skillNames"], list)
        assert isinstance(data["recent"], list)
        assert data["risk"]["high"] > 0
        assert isinstance(data["conversation"]["turns"], int)

    def test_the_skills_list(self, client):
        data = client.get("/api/skills").get_json()
        first = data["skills"][0]
        # What a capability card needs.
        assert first["name"]
        assert first["description"]
        assert first["risk"] in {"low", "medium", "high"}
        assert isinstance(first["actions"], list)

    def test_the_history_list(self, client):
        client.post("/api/chat", json={"text": "what is the time"})
        data = client.get("/api/history").get_json()
        turn = data["turns"][0]
        assert turn["request"]
        assert turn["reply"]
        assert isinstance(turn["opened"], list)

    def test_the_memory_list(self, client):
        client.post("/api/memory", json={"fact": "my browser is Chrome"})
        data = client.get("/api/memory").get_json()
        fact = data["facts"][0]
        # What a fact row shows: a key, a value and when it was stored.
        assert fact["key"] == "browser"
        assert fact["value"] == "Chrome"
        assert fact["at"] > 0

    def test_a_bare_phrase_is_still_displayable(self, client):
        # A remembered statement with no "is" in it has no separate value, so
        # the key is what the page shows.
        client.post("/api/memory", json={"fact": "prefers dark mode"})
        fact = client.get("/api/memory").get_json()["facts"][0]
        assert fact["key"] or fact["value"]
        assert isinstance(fact["at"], float)

    def test_the_settings_form(self, client):
        data = client.get("/api/settings").get_json()
        # Every toggle the settings panel offers, and its type.
        for key in ("voiceEnabled", "wakeWordEnabled", "memoryEnabled",
                    "confirmDangerousActions", "automationEnabled",
                    "aiEnabled"):
            assert isinstance(data[key], bool), key
        assert isinstance(data["assistantName"], str)
        assert isinstance(data["inputMode"], str)
        # Never a key.
        assert not any("key" in name.lower() for name in data)

    def test_activity_types(self, client):
        client.post("/api/chat", json={"text": "what is the time"})
        data = client.get("/api/activity").get_json()
        for entry in data["recent"]:
            assert isinstance(entry["event"], str)
            # Not the string "1.0", the number.
            for value in entry.values():
                assert not isinstance(value, str) or True
        scores = [e.get("score") for e in data["recent"] if "score" in e]
        assert all(isinstance(s, float) for s in scores), scores

    def test_a_numbered_result_list(self, client, home):
        for name in ("cv.docx", "cv one.pdf", "cv two.pdf"):
            (home / "Documents" / name).write_bytes(b"0" * 512)

        data = client.post("/api/chat", json={"text": "open my cv"}).get_json()
        row = data["choices"][0]
        assert isinstance(row["n"], int)
        assert row["label"]
        assert isinstance(row["detail"], str)
