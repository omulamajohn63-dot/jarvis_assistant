"""Reading configuration from the environment and from .env.

Settings are loaded once into a frozen object and then passed to whatever needs
them, rather than being read out of the environment at every call site. That is
what lets a test run the assistant with a different configuration from the one
the developer's machine has.

.env is parsed here rather than with a library: it is fifteen lines of reading,
and a dependency that only exists to read KEY=value files is not worth carrying.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from jarvis2.config import defaults

# What the input mode may be. Anything else would leave the assistant with no
# way to be talked to.
INPUT_MODES = frozenset({"voice", "keyboard", "web"})


def parse_dotenv(text: str) -> dict:
    """Reads KEY=value lines out of the text of a .env file.

    Understands the forms a person actually types: blank lines, comments, an
    optional `export`, and a value quoted with either quote style.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()

        key, separator, value = line.partition("=")
        if not separator:
            continue

        key = key.strip()
        if not key:
            continue

        value = value.strip()
        # A quoted value is taken as written, so a trailing comment inside it is
        # part of the value rather than a comment.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()

        values[key] = value
    return values


def load_dotenv(path: str | Path) -> dict:
    """Reads a .env file. A missing file is not an error."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return {}
    except OSError:
        return {}
    return parse_dotenv(text)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_int(name: str, value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a whole number, got {value!r}") from None


def _as_float(name: str, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None


@dataclass(frozen=True)
class Settings:
    """Everything the assistant can be told to do differently.

    Frozen so that a component cannot quietly change another's configuration by
    editing a shared object.
    """

    # identity
    assistant_name: str = defaults.ASSISTANT_NAME
    user_name: str = defaults.USER_NAME

    # voice
    voice_enabled: bool = defaults.VOICE_ENABLED
    voice_index: int = defaults.VOICE_INDEX
    voice_rate: int = defaults.VOICE_RATE
    voice_volume: float = defaults.VOICE_VOLUME
    recognition_language: str = defaults.RECOGNITION_LANGUAGE
    listen_timeout: int = defaults.LISTEN_TIMEOUT
    input_mode: str = defaults.INPUT_MODE
    wake_word_enabled: bool = defaults.WAKE_WORD_ENABLED
    wake_word: str = defaults.WAKE_WORD
    google_speech_api_key: str = ""

    # ai
    ai_enabled: bool = defaults.AI_ENABLED
    ai_provider: str = defaults.AI_PROVIDER
    ai_model: str = defaults.AI_MODEL
    ai_api_key: str = defaults.AI_API_KEY
    ai_base_url: str = defaults.AI_BASE_URL
    google_api_key: str = defaults.GOOGLE_API_KEY
    ai_timeout: float = defaults.AI_TIMEOUT
    ai_max_tokens: int = defaults.AI_MAX_TOKENS
    ai_history_turns: int = defaults.AI_HISTORY_TURNS
    ai_history_chars: int = defaults.AI_HISTORY_CHARS

    # memory
    memory_enabled: bool = defaults.MEMORY_ENABLED
    memory_dir: str = defaults.MEMORY_DIR
    memory_max_facts: int = defaults.MEMORY_MAX_FACTS

    # safety
    confirm_dangerous_actions: bool = defaults.CONFIRM_DANGEROUS_ACTIONS
    require_confirmation_for_medium_risk: bool = (
        defaults.REQUIRE_CONFIRMATION_FOR_MEDIUM_RISK
    )
    protected_directories: tuple = defaults.PROTECTED_DIRECTORIES

    # browser
    host: str = defaults.HOST
    port: int = defaults.PORT
    sample_rate: int = defaults.SAMPLE_RATE
    sample_width: int = defaults.SAMPLE_WIDTH
    max_recording_seconds: int = defaults.MAX_RECORDING_SECONDS

    # web
    lookup_timeout: int = defaults.LOOKUP_TIMEOUT
    read_char_limit: int = defaults.READ_CHAR_LIMIT
    results_page_size: int = defaults.RESULTS_PAGE_SIZE

    # automation
    automation_enabled: bool = defaults.AUTOMATION_ENABLED

    # logging
    log_level: str = defaults.LOG_LEVEL
    log_file: str = defaults.LOG_FILE

    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    def __post_init__(self):
        """Refuses values that would make the assistant behave strangely.

        Checked here rather than at each use, because a setting that quietly
        holds a nonsense value is far more confusing than a message at the point
        it was set.
        """
        if self.input_mode not in INPUT_MODES:
            raise ValueError(
                f"input_mode must be one of {sorted(INPUT_MODES)}, "
                f"got {self.input_mode!r}"
            )

        if not 1 <= self.port <= 65535:
            raise ValueError(f"port must be 1 to 65535, got {self.port}")

        if not 0.0 <= self.voice_volume <= 1.0:
            raise ValueError(
                f"voice_volume must be 0 to 1, got {self.voice_volume}"
            )

        if self.voice_rate < 50 or self.voice_rate > 400:
            raise ValueError(
                f"voice_rate must be 50 to 400, got {self.voice_rate}"
            )

        if self.voice_index < 0:
            raise ValueError(
                f"voice_index cannot be negative, got {self.voice_index}"
            )

        if self.ai_history_turns < 0:
            raise ValueError("ai_history_turns cannot be negative")

        if self.read_char_limit <= 0:
            raise ValueError("read_char_limit must be at least one character")

        if self.memory_max_facts <= 0:
            raise ValueError("memory_max_facts must be at least one")

        if self.protected_directories and not isinstance(
            self.protected_directories, tuple
        ):
            raise ValueError("protected_directories must be a tuple")

    # ------------------------------------------------------------------
    # Secrets never appear in a repr, a log line or a traceback.
    # ------------------------------------------------------------------
    def __repr__(self) -> str:
        pairs = ", ".join(
            f"{f.name}={shown(self, f.name)}" for f in fields(self)
            if f.name != "extra"
        )
        return f"Settings({pairs})"

    __str__ = __repr__

    @property
    def secrets(self) -> dict:
        """The configured secrets, for handing to a provider."""
        return {
            name: getattr(self, name)
            for name in SECRET_FIELDS
            if getattr(self, name)
        }

    @property
    def has_ai(self) -> bool:
        """True when a provider is configured well enough to be worth trying."""
        if not self.ai_enabled or not self.ai_provider:
            return False
        if self.ai_provider == "gemini":
            return bool(self.google_api_key and self.ai_model)
        if self.ai_provider in {"mock", "echo"}:
            return True
        return bool(self.ai_api_key and self.ai_model)

    @property
    def public_summary(self) -> dict:
        """What the dashboard shows about the configuration. No secrets."""
        return {
            "assistantName": self.assistant_name,
            "voiceEnabled": self.voice_enabled,
            "inputMode": self.input_mode,
            "wakeWordEnabled": self.wake_word_enabled,
            "wakeWord": self.wake_word if self.wake_word_enabled else None,
            "voiceRate": self.voice_rate,
            "voiceVolume": self.voice_volume,
            "aiEnabled": self.ai_enabled,
            "aiProvider": self.ai_provider or None,
            "aiModel": self.ai_model or None,
            "aiConfigured": self.has_ai,
            "memoryEnabled": self.memory_enabled,
            "confirmDangerousActions": self.confirm_dangerous_actions,
            "automationEnabled": self.automation_enabled,
        }

    def with_overrides(self, **changes) -> Settings:
        """A copy with some values replaced, for the settings API and for tests."""
        unknown = set(changes) - {f.name for f in fields(self)}
        if unknown:
            raise ValueError(f"unknown settings: {sorted(unknown)}")
        return replace(self, **changes)


SECRET_FIELDS = frozenset({
    "ai_api_key",
    "google_api_key",
    "google_speech_api_key",
})


def shown(settings: Settings, name: str) -> str:
    """How one setting appears in a repr. A secret never appears at all."""
    if name in SECRET_FIELDS:
        return "'[redacted]'"
    return repr(getattr(settings, name))


# The environment variable behind each setting. Grouped by prefix so related
# settings read together in .env.example.
ENVIRONMENT = {
    "assistant_name": "JARVIS_NAME",
    "user_name": "USER_NAME",
    "voice_enabled": "VOICE_ENABLED",
    "voice_index": "VOICE_INDEX",
    "voice_rate": "VOICE_RATE",
    "voice_volume": "VOICE_VOLUME",
    "recognition_language": "RECOGNITION_LANGUAGE",
    "listen_timeout": "LISTEN_TIMEOUT",
    "input_mode": "INPUT_MODE",
    "wake_word_enabled": "WAKE_WORD_ENABLED",
    "wake_word": "WAKE_WORD",
    "google_speech_api_key": "GOOGLE_SPEECH_API_KEY",
    "ai_enabled": "AI_ENABLED",
    "ai_provider": "AI_PROVIDER",
    "ai_model": "AI_MODEL",
    "ai_api_key": "AI_API_KEY",
    "ai_base_url": "AI_BASE_URL",
    "google_api_key": "GOOGLE_API_KEY",
    "ai_timeout": "AI_TIMEOUT",
    "ai_max_tokens": "AI_MAX_TOKENS",
    "ai_history_turns": "AI_HISTORY_TURNS",
    "ai_history_chars": "AI_HISTORY_CHARS",
    "memory_enabled": "MEMORY_ENABLED",
    "memory_dir": "MEMORY_DIR",
    "memory_max_facts": "MEMORY_MAX_FACTS",
    "confirm_dangerous_actions": "CONFIRM_DANGEROUS_ACTIONS",
    "require_confirmation_for_medium_risk": "CONFIRM_MEDIUM_RISK",
    "host": "HOST",
    "port": "PORT",
    "lookup_timeout": "LOOKUP_TIMEOUT",
    "read_char_limit": "READ_CHAR_LIMIT",
    "results_page_size": "RESULTS_PAGE_SIZE",
    "automation_enabled": "AUTOMATION_ENABLED",
    "log_level": "LOG_LEVEL",
    "log_file": "LOG_FILE",
}

# Settings read as a number or a flag rather than as text.
BOOLEAN_SETTINGS = frozenset({
    "voice_enabled", "wake_word_enabled", "ai_enabled", "memory_enabled",
    "confirm_dangerous_actions", "require_confirmation_for_medium_risk",
    "automation_enabled",
})
INTEGER_SETTINGS = frozenset({
    "voice_index", "voice_rate", "listen_timeout", "ai_max_tokens",
    "ai_history_turns", "ai_history_chars", "memory_max_facts", "port",
    "lookup_timeout", "read_char_limit", "results_page_size",
})
FLOAT_SETTINGS = frozenset({"voice_volume", "ai_timeout"})

# The other way round, so a mapping keyed by variable name can be read too.
BY_VARIABLE = {variable: name for name, variable in ENVIRONMENT.items()}


def _setting_name(key: str) -> str | None:
    """The setting a key names, whichever spelling it used.

    Both ``voice_enabled`` and ``VOICE_ENABLED`` are natural at a call site, so
    both work. Having one of them silently do nothing would be a trap.
    """
    if key in ENVIRONMENT:
        return key
    return BY_VARIABLE.get(key)


def settings_from(source: dict, root: str | Path | None = None) -> Settings:
    """Builds settings from a mapping, applying the right type to each name.

    Accepts either the setting name (``voice_enabled``) or the environment
    variable behind it (``VOICE_ENABLED``).

    A bad value is an error rather than something silently ignored, because a
    port that quietly stayed at 8765 would be far more confusing than a message.
    """
    values: dict[str, Any] = {}
    problems: list[str] = []

    for key, raw in source.items():
        name = _setting_name(key)
        if name is None:
            continue
        try:
            if name in BOOLEAN_SETTINGS:
                values[name] = _as_bool(raw)
            elif name in INTEGER_SETTINGS:
                values[name] = _as_int(ENVIRONMENT[name], raw)
            elif name in FLOAT_SETTINGS:
                values[name] = _as_float(ENVIRONMENT[name], raw)
            else:
                values[name] = str(raw)
        except ValueError as error:
            problems.append(str(error))

    if problems:
        raise ValueError("; ".join(problems))

    settings = Settings(**values)
    if root is not None:
        settings = replace(settings, extra={"root": str(root)})
    return settings


def load_settings(
    env: dict | None = None,
    dotenv: str | Path | None = None,
    root: str | Path | None = None,
    **overrides,
) -> Settings:
    """Loads settings the way the assistant does at startup.

    Precedence, highest first: explicit overrides, the real environment, .env,
    then the built-in defaults. The real environment beating .env is what lets a
    shell command override a file for one run.
    """
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    environment = os.environ if env is None else env

    merged: dict[str, Any] = {}
    for candidate in (root / ".env", Path(".env")):
        merged.update(load_dotenv(candidate))
    if dotenv is not None:
        merged.update(load_dotenv(dotenv))

    # The environment is keyed by variable name, so it is translated rather than
    # merged directly.
    for name, variable in ENVIRONMENT.items():
        if variable in environment:
            merged[name] = environment[variable]

    settings = settings_from(merged, root=root)
    if overrides:
        settings = settings.with_overrides(**overrides)
    return settings
