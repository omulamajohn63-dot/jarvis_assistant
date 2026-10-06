"""Memory: what is kept, what is refused, and how it is got rid of."""

import json

import pytest

from jarvis2.core.memory import LongTermMemory, MemoryStore, Preferences, is_refused

# Assembled from parts so that no scanner reading this repository mistakes a
# fixture for a real key. The patterns still match, which is the point.
FAKE_OPENAI = "sk-" + "abc123def456ghi789jkl012"
FAKE_GOOGLE = "AIzaSy" + "D-1234567890abcdefghijklmnop"
FAKE_GITHUB = "ghp_" + "abc123def456ghi789"


class TestWhatIsRefused:
    @pytest.mark.parametrize("text", [
        f"my api key is {FAKE_OPENAI}",
        FAKE_GOOGLE,
        f"my access token is {FAKE_GITHUB}",
        "the password is hunter2",
        "my password is correct horse battery staple",
        "my credit card is 4111 1111 1111 1111",
        "my social security is 123-45-6789",
        "someone@example.com is who emailed me",
    ])
    def test_secrets_and_identifiers_are_refused(self, text):
        # A memory is read back out loud and sent to a model, so a key in one
        # would be a real leak.
        reason = is_refused(text)
        assert reason, f"{text!r} should have been refused"

    def test_the_reason_can_be_said(self):
        assert "password" in is_refused("my password is hunter2")

    @pytest.mark.parametrize("key,value", [
        ("key", FAKE_OPENAI),
        ("key", FAKE_GOOGLE),
        ("key", FAKE_GITHUB),
        ("password", "hunter2"),
    ])
    def test_the_store_refuses_them(self, tmp_path, key, value):
        store = MemoryStore(tmp_path)
        assert store.remember(key, value) is None
        assert store.facts() == []


class TestMemoryStore:
    def test_it_starts_empty(self, tmp_path):
        store = MemoryStore(tmp_path)
        assert store.facts() == []

    def test_something_is_kept(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.remember("preference", "dark mode")
        assert store.facts() == ["dark mode"]

    def test_it_survives_a_restart(self, tmp_path):
        MemoryStore(tmp_path).remember("preference", "dark mode")
        # A second store is a new session reading the same file.
        assert MemoryStore(tmp_path).facts() == ["dark mode"]

    @pytest.mark.parametrize("text", [
        "I prefer dark mode",
        "my browser is Chrome",
        "the project is called Jarvis",
        "I work in the mornings",
    ])
    def test_ordinary_things_are_fine(self, text):
        assert is_refused(text) == ""

    def test_a_secret_is_refused(self, tmp_path):
        store = MemoryStore(tmp_path)
        assert store.remember("key", FAKE_OPENAI) is None
        assert store.facts() == []

    def test_the_same_key_is_updated_not_duplicated(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.remember("browser", "Chrome")
        store.remember("browser", "Edge")
        assert store.facts() == ["Edge"]
        assert len(store) == 1

    def test_a_recall_by_key(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.remember("browser", "Chrome")
        assert store.recall("browser").value == "Chrome"
        assert store.recall("browser") is not None

    def test_a_recall_is_case_insensitive(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.remember("Browser", "Chrome")
        assert store.recall("browser") is not None

    def test_something_can_be_forgotten(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.remember("browser", "Chrome")
        assert store.forget("browser") is True
        assert store.facts() == []

    def test_forgetting_something_absent_says_so(self, tmp_path):
        assert MemoryStore(tmp_path).forget("nothing") is False

    def test_the_last_can_be_forgotten(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.remember("a", "1")
        store.remember("b", "2")
        assert store.forget_last() is True
        assert store.facts() == ["1"]

    def test_everything_can_be_cleared(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.remember("a", "1")
        store.clear()
        assert store.facts() == []

    def test_disabled_memory_stores_nothing(self, tmp_path):
        store = MemoryStore(tmp_path, enabled=False)
        assert store.remember("a", "1") is None
        assert store.facts() == []

    def test_a_disabled_store_is_falsy(self, tmp_path):
        # So a caller can say "memory is off" plainly rather than crashing on an
        # empty store.
        assert bool(MemoryStore(tmp_path, enabled=False)) is False

    def test_an_enabled_but_empty_store_is_truthy(self, tmp_path):
        assert bool(MemoryStore(tmp_path)) is True

    def test_it_stays_within_its_limit(self, tmp_path):
        store = MemoryStore(tmp_path, max_facts=3)
        for n in range(10):
            store.remember(f"key{n}", str(n))
        assert len(store) == 3
        # The oldest go, so a long-lived store stays about the user.
        assert store.facts() == ["7", "8", "9"]

    def test_the_file_is_valid_json(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.remember("a", "1")
        payload = json.loads(store.path.read_text(encoding="utf-8"))
        assert payload["facts"][0]["key"] == "a"

    def test_a_corrupt_file_does_not_break_starting(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("{not json", encoding="utf-8")

        # Reads as empty rather than raising, because a memory file is not worth
        # refusing to start over.
        assert store.facts() == []

    def test_a_corrupt_file_is_kept_for_looking_at(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("{not json", encoding="utf-8")
        store.facts()
        # Moved aside rather than deleted, so whatever was in it can be read.
        assert store.path.with_suffix(".corrupt.json").exists()

    def test_an_empty_store_is_described(self, tmp_path):
        described = MemoryStore(tmp_path).describe()
        assert described["enabled"] is True
        assert described["count"] == 0


class TestFactSplitting:
    @pytest.mark.parametrize("key,expected_key,expected_value", [
        ("my browser is Chrome", "browser", "Chrome"),
        ("browser is Chrome", "browser", "Chrome"),
        ("browser = Chrome", "browser", "Chrome"),
        ("i prefer dark mode", "dark mode", ""),
        ("dark mode", "dark mode", ""),
    ])
    def test_a_statement_is_taken_apart(self, key, expected_key, expected_value):
        store = MemoryStore.__new__(MemoryStore)
        store.enabled = True
        from jarvis2.core.memory import _split

        assert _split(key, "") == (expected_key, expected_value)

    def test_a_key_and_a_value_given_separately_are_kept(self, tmp_path):
        store = MemoryStore(tmp_path)
        store.remember("browser", "Chrome")
        assert store.facts() == ["Chrome"]


class TestLongTermMemory:
    def test_it_wraps_the_store(self, tmp_path):
        memory = LongTermMemory(MemoryStore(tmp_path))
        memory.remember("preference", "dark mode")
        assert memory.facts() == ["dark mode"]

    def test_it_can_be_described_for_the_dashboard(self, tmp_path):
        memory = LongTermMemory(MemoryStore(tmp_path))
        memory.remember("browser", "Chrome")
        described = memory.describe()
        assert described["count"] == 1
        assert described["keys"] == ["browser"]


class TestPreferences:
    @pytest.fixture
    def preferences(self, tmp_path, settings):
        return Preferences(LongTermMemory(MemoryStore(tmp_path)), settings)

    def test_a_known_preference_is_stored(self, preferences):
        result = preferences.set("browser", "Chrome")
        assert result["preference"] == "preferred_browser"

    def test_an_unknown_preference_is_refused(self, preferences):
        assert preferences.set("favourite colour", "blue") is None

    def test_the_assistant_name_can_be_set(self, preferences):
        preferences.set("name", "Friday")
        assert preferences.settings.assistant_name == "Friday"

    def test_a_secret_preference_is_refused(self, preferences):
        result = preferences.set("browser", "sk-" + "abc123def456ghi789")
        assert result is None

    def test_a_volume_is_converted_to_a_number(self, preferences):
        preferences.set("volume", "50")
        assert 0 <= preferences.settings.voice_volume <= 1

    def test_it_can_be_read_back(self, preferences):
        preferences.set("browser", "Chrome")
        assert preferences.get("browser").value == "Chrome"

    def test_it_becomes_a_prompt_block(self, preferences):
        preferences.set("browser", "Chrome")
        assert "Chrome" in preferences.as_prompt_block()
