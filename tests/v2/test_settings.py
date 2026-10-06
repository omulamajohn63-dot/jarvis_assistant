"""Configuration: reading it, typing it, and keeping secrets out of it."""

import dataclasses

import pytest

from jarvis2.config.settings import (
    ENVIRONMENT,
    SECRET_FIELDS,
    Settings,
    load_dotenv,
    load_settings,
    parse_dotenv,
    settings_from,
)


class TestParseDotenv:
    def test_a_simple_pair(self):
        assert parse_dotenv("PORT=8765") == {"PORT": "8765"}

    def test_comments_and_blank_lines(self):
        text = "# a comment\n\nPORT=1234\n\n# another\n"
        assert parse_dotenv(text) == {"PORT": "1234"}

    def test_export_prefix(self):
        assert parse_dotenv("export PORT=1234") == {"PORT": "1234"}

    def test_quoted_value_keeps_its_spaces(self):
        assert parse_dotenv('KEY="a b c"') == {"KEY": "a b c"}

    def test_single_quotes(self):
        assert parse_dotenv("KEY='a b'") == {"KEY": "a b"}

    def test_a_hash_inside_quotes_is_part_of_the_value(self):
        assert parse_dotenv('KEY="a # b"') == {"KEY": "a # b"}

    def test_a_trailing_comment_is_dropped(self):
        assert parse_dotenv("PORT=1234 # the port") == {"PORT": "1234"}

    def test_a_line_without_an_equals_is_skipped(self):
        assert parse_dotenv("JUST A LINE") == {}

    def test_an_empty_value(self):
        assert parse_dotenv("KEY=") == {"KEY": ""}

    def test_no_trailing_newline_needed(self):
        assert parse_dotenv("A=1\nB=2") == {"A": "1", "B": "2"}

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        assert load_dotenv(tmp_path / "nothing.env") == {}


class TestTypes:
    @pytest.mark.parametrize("raw,expected", [
        ("true", True), ("True", True), ("1", True), ("yes", True),
        ("on", True), ("false", False), ("0", False), ("no", False),
        ("", False),
    ])
    def test_booleans(self, raw, expected):
        settings = settings_from({"VOICE_ENABLED": raw})
        assert settings.voice_enabled is expected

    def test_numbers(self):
        settings = settings_from({"PORT": "9000", "VOICE_RATE": "200"})
        assert settings.port == 9000
        assert settings.voice_rate == 200

    def test_floats(self):
        settings = settings_from({"VOICE_VOLUME": "0.5"})
        assert settings.voice_volume == 0.5

    def test_a_bad_number_is_an_error(self):
        # Silently keeping the default would be far more confusing than this.
        with pytest.raises(ValueError, match="whole number"):
            settings_from({"PORT": "eight thousand"})

    def test_a_bad_float_is_an_error(self):
        with pytest.raises(ValueError, match="must be a number"):
            settings_from({"VOICE_VOLUME": "loud"})

    def test_several_bad_values_are_all_reported(self):
        with pytest.raises(ValueError) as caught:
            settings_from({"PORT": "x", "VOICE_RATE": "y"})
        assert "PORT" in str(caught.value)
        assert "VOICE_RATE" in str(caught.value)

    def test_text_stays_text(self):
        assert settings_from({"JARVIS_NAME": "Friday"}).assistant_name == "Friday"


class TestSecrets:
    # Assembled from parts so no scanner mistakes a fixture for a real key. The
    # pattern still matches, which is what is being tested.
    FAKE = "sk-" + "abcdef1234567890abcdef"

    def test_a_secret_never_appears_in_the_repr(self):
        settings = Settings(ai_api_key=self.FAKE)
        # A repr is what ends up in a log or a traceback.
        assert self.FAKE not in repr(settings)
        assert "redacted" in repr(settings)

    def test_nor_in_str(self):
        settings = Settings(google_api_key="AIza" + "SySomethingSomething1234")
        assert "AIza" not in str(settings)

    @pytest.mark.parametrize("field", sorted(SECRET_FIELDS))
    def test_every_secret_field_is_hidden(self, field):
        settings = Settings(**{field: "supersecretvalue"})
        assert "supersecretvalue" not in repr(settings)

    def test_the_public_summary_has_no_secrets(self):
        settings = Settings(
            ai_api_key=self.FAKE, google_api_key="AIza" + "Secret",
            ai_provider="openai", ai_model="gpt")
        summary = settings.public_summary
        assert self.FAKE not in str(summary)
        assert "AIzaSecret" not in str(summary)

    def test_secrets_are_available_to_a_provider(self):
        settings = Settings(ai_api_key=self.FAKE,
                            google_api_key="AIza" + "Thing")
        assert settings.secrets == {"ai_api_key": self.FAKE,
                                    "google_api_key": "AIzaThing"}


class TestOverrides:
    def test_an_override_replaces_one_value(self):
        settings = Settings().with_overrides(assistant_name="Friday")
        assert settings.assistant_name == "Friday"

    def test_the_original_is_unchanged(self):
        original = Settings()
        original.with_overrides(assistant_name="Friday")
        assert original.assistant_name == "Jarvis"

    def test_an_unknown_name_is_refused(self):
        with pytest.raises(ValueError, match="unknown settings"):
            Settings().with_overrides(nonsense=True)

    def test_settings_are_frozen(self):
        # Frozen so one component cannot quietly change another's setup.
        with pytest.raises(dataclasses.FrozenInstanceError):
            Settings().assistant_name = "Something"


class TestHasAI:
    def test_nothing_configured(self):
        assert Settings().has_ai is False

    def test_disabled(self):
        assert Settings(ai_provider="openai", ai_model="gpt",
                        ai_api_key="k", ai_enabled=False).has_ai is False

    def test_a_provider_with_a_key_and_model(self):
        assert Settings(ai_provider="openai", ai_model="gpt",
                        ai_api_key="k").has_ai is True

    def test_openai_without_a_key(self):
        assert Settings(ai_provider="openai", ai_model="gpt").has_ai is False

    def test_gemini_needs_the_google_key_not_the_openai_one(self):
        # The two providers use different keys, and using the wrong one is a
        # confusing failure rather than an obvious one.
        assert Settings(ai_provider="gemini", ai_model="gemini-2.0-flash",
                        ai_api_key="sk-openai").has_ai is False
        assert Settings(ai_provider="gemini", ai_model="gemini-2.0-flash",
                        google_api_key="AIzaG").has_ai is True


class TestLoadSettings:
    def test_the_environment_is_read(self, tmp_path):
        settings = load_settings(env={"PORT": "9999"}, root=tmp_path)
        assert settings.port == 9999

    def test_a_dotenv_is_read(self, tmp_path):
        (tmp_path / ".env").write_text("JARVIS_NAME=Friday\n", encoding="utf-8")
        assert load_settings(env={}, root=tmp_path).assistant_name == "Friday"

    def test_the_environment_beats_the_file(self, tmp_path):
        # So a shell command can override a file for one run.
        (tmp_path / ".env").write_text("PORT=1111\n", encoding="utf-8")
        settings = load_settings(env={"PORT": "2222"}, root=tmp_path)
        assert settings.port == 2222

    def test_explicit_overrides_beat_everything(self, tmp_path):
        settings = load_settings(env={"PORT": "2222"}, root=tmp_path,
                                 port=3333)
        assert settings.port == 3333

    def test_the_root_is_kept_for_other_purposes(self, tmp_path):
        settings = load_settings(env={}, root=tmp_path)
        assert settings.extra["root"] == str(tmp_path)

    def test_with_nothing_configured_the_defaults_apply(self, tmp_path):
        settings = load_settings(env={}, root=tmp_path)
        assert settings.assistant_name == "Jarvis"
        assert settings.host == "127.0.0.1"
        assert settings.port == 8765


class TestEnvironmentMap:
    def test_every_variable_is_unique(self):
        values = list(ENVIRONMENT.values())
        assert len(values) == len(set(values))

    def test_every_variable_is_upper_case(self):
        for name, variable in ENVIRONMENT.items():
            assert variable == variable.upper(), name

    @pytest.mark.parametrize("variable", ["PORT", "JARVIS_NAME", "AI_API_KEY",
                                          "MEMORY_ENABLED",
                                          "CONFIRM_DANGEROUS_ACTIONS"])
    def test_the_documented_variables_are_present(self, variable):
        # These are the ones .env.example tells people about.
        assert variable in ENVIRONMENT.values()
