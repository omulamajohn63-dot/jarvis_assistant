"""Memory.

Kept apart from the conversation on purpose. The conversation is what happened
just now and is forgotten when the session ends; memory is what was worth
keeping, it survives a restart, and nothing is stored unless it was asked for.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from jarvis2.logging_utils import get_logger, redact

_log = get_logger("memory")

# Anything matching these is never stored. A memory is read back out loud and
# sent to a model, so a key or a password in one would be a real leak.
SECRET_PATTERNS = re.compile(
    r"(?i)("
    r"sk-[A-Za-z0-9]{16,}"
    r"|AIza[0-9A-Za-z\-_]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|\b(?:api[_-]?key|password|passwd|secret|access[_-]?token|refresh[_-]?token"
    r"|private[_-]?key|credit[_-]?card|ssn|social[_-]?security)\b"
    r")"
)

# Details that identify somebody and are not asked for. Held to a pattern rather
# than a list, because a list is always incomplete.
PRIVATE_PATTERNS = re.compile(
    r"(?i)("
    r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"          # email addresses
    r"|\b\+?\d[\d\s().-]{8,}\d\b"            # phone numbers
    r"|\b\d{3}-\d{2}-\d{4}\b"                # national id
    r"|\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b"    # card numbers
    r"|\bmy address is\b"
    r"|\bdate of birth\b"
    r")"
)


@dataclass
class Fact:
    """One remembered thing."""

    key: str
    value: str
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return asdict(self)


def is_refused(text: str) -> str:
    """Why a fact may not be stored, or an empty string when it may.

    Returns the reason rather than a bare bool, so the user can be told why
    rather than just refused.
    """
    if SECRET_PATTERNS.search(text):
        return "it looks like a password or a key"
    if PRIVATE_PATTERNS.search(text):
        return "it looks like private information"
    return ""


class MemoryStore:
    """A small JSON file of facts, written atomically.

    Atomic because a half-written memory file is worse than none: it would be
    read back as real facts, or fail to load and take the assistant with it.
    """

    FILENAME = "memory.json"

    def __init__(self, directory: str | Path, max_facts: int = 500,
                 enabled: bool = True):
        self.directory = Path(directory)
        self.path = self.directory / self.FILENAME
        self.max_facts = max_facts
        self.enabled = enabled
        self._facts: list = []
        self._loaded = False

    # ------------------------------------------------------------------
    def load(self) -> list:
        if self._loaded:
            return self._facts

        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._facts = []
            return self._facts
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
            # A corrupt file is moved aside rather than deleted, so whatever was
            # in it can still be looked at.
            _log.warning("memory file could not be read: %s", error)
            self._quarantine()
            self._facts = []
            return self._facts

        facts = []
        for entry in raw.get("facts", []) if isinstance(raw, dict) else []:
            if isinstance(entry, dict) and entry.get("key"):
                facts.append(Fact(
                    key=str(entry["key"]),
                    value=str(entry.get("value", "")),
                    at=float(entry.get("at", 0.0)),
                ))
        self._facts = facts
        return self._facts

    def _quarantine(self) -> None:
        try:
            self.path.replace(self.path.with_suffix(".corrupt.json"))
        except OSError:
            pass

    def _write(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "facts": [fact.as_dict() for fact in self._facts],
        }
        handle, temporary = tempfile.mkstemp(
            dir=str(self.directory), suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
            os.replace(temporary, self.path)
        except OSError as error:
            _log.error("could not write memory: %s", error)
            try:
                os.unlink(temporary)
            except OSError:
                pass

    # ------------------------------------------------------------------
    def remember(self, key: str, value: str = "") -> Fact | None:
        """Stores something, or refuses and returns None.

        Refusing is silent to the model and loud to the user: the caller turns a
        None into an explanation rather than a false agreement.
        """
        if not self.enabled:
            return None

        key, value = _split(key, value)
        if not key:
            return None

        reason = is_refused(f"{key} {value}")
        if reason:
            _log.info("refused to remember something: %s", reason)
            return None

        facts = self.load()
        for fact in facts:
            if fact.key.lower() == key.lower():
                fact.value = value
                fact.at = time.time()
                self._write()
                return fact

        fact = Fact(key=key, value=value)
        facts.append(fact)

        # The oldest go first, so a long-lived store stays about the user rather
        # than about everything ever said.
        while len(facts) > self.max_facts:
            facts.pop(0)

        self._write()
        _log.info("remembered %s", redact(key))
        return fact

    def recall(self, key: str) -> Fact | None:
        wanted = key.strip().lower()
        for fact in self.load():
            if fact.key.lower() == wanted:
                return fact
        return None

    def facts(self) -> list:
        return [fact.value or fact.key for fact in self.load()]

    def all_facts(self) -> list:
        return list(self.load())

    def forget(self, key: str) -> bool:
        facts = self.load()
        wanted = key.strip().lower()
        remaining = [fact for fact in facts if fact.key.lower() != wanted]
        if len(remaining) == len(facts):
            return False
        self._facts = remaining
        self._write()
        return True

    def forget_last(self) -> bool:
        facts = self.load()
        if not facts:
            return False
        self._facts = facts[:-1]
        self._write()
        return True

    def clear(self) -> None:
        self._facts = []
        self._write()

    def __len__(self) -> int:
        return len(self.load())

    def __bool__(self) -> bool:
        # An empty store is still a store, so this is True whenever memory is on.
        return self.enabled

    def describe(self) -> dict:
        return {
            "enabled": self.enabled,
            "count": len(self.load()),
            "path": str(self.path),
            "keys": [fact.key for fact in self.load()],
        }


def _split(key: str, value: str) -> tuple:
    """Reads "my browser is chrome" as key "browser", value "chrome"."""
    key = (key or "").strip()
    if value:
        return key, value.strip()

    # Checked before the leading words are stripped, or "i prefer dark mode"
    # loses its "i " and then matches none of the patterns below.
    patterns = (r"^i\s+(?:prefer|like|use|want|always)\s+(.+)$",
                r"^my\s+(.+?)\s+is\s+(.+)$",
                r"^(.+?)\s+is\s+(.+)$",
                r"^(.+?)\s*=\s*(.+)$")
    for pattern in patterns:
        match = re.match(pattern, key, flags=re.IGNORECASE)
        if match:
            groups = match.groups()
            if len(groups) == 1:
                return groups[0].strip(), ""
            return groups[0].strip(), groups[1].strip()

    for prefix in ("that i ", "that ", "my "):
        if key.lower().startswith(prefix):
            return key[len(prefix):].strip(), ""

    return key, ""


class LongTermMemory:
    """The memory the assistant is allowed to keep between sessions."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def remember(self, key: str, value: str = "") -> Fact | None:
        return self.store.remember(key, value)

    def recall(self, key: str) -> Fact | None:
        return self.store.recall(key)

    def facts(self) -> list:
        return self.store.facts()

    def forget(self, key: str) -> bool:
        return self.store.forget(key)

    def forget_last(self) -> bool:
        return self.store.forget_last()

    def clear(self) -> None:
        self.store.clear()

    def describe(self) -> dict:
        return self.store.describe()


class Preferences:
    """Settings the user has stated, kept apart from files.

    A preference is a fact about how they like things to work, so it is stored
    as a memory fact and applied to the running settings when it is set.
    """

    # What each remembered preference changes.
    APPLIES = {
        "browser": "preferred_browser",
        "voice": "preferred_voice",
        "language": "preferred_language",
        "name": "assistant_name",
        "my name": "user_name",
        "units": "units",
        "volume": "voice_volume",
    }

    def __init__(self, memory: LongTermMemory, settings=None):
        self.memory = memory
        self.settings = settings

    def set(self, key: str, value: str) -> dict | None:
        field_name = self._field_for(key)
        if not field_name:
            return None

        fact = self.memory.remember(field_name, value)
        if fact is None:
            return None

        if self.settings is not None and field_name in {
            "assistant_name", "user_name", "voice_volume",
        }:
            from jarvis2.config.settings import Settings

            names = {f.name for f in Settings.__dataclass_fields__.values()}
            if field_name in names:
                self.settings = self.settings.with_overrides(
                    **{field_name: _coerce(field_name, value)}
                )
        return {"preference": field_name, "value": value}

    def get(self, key: str):
        field_name = self._field_for(key)
        if not field_name:
            return None
        return self.memory.recall(field_name)

    def _field_for(self, key: str) -> str:
        wanted = key.strip().lower()
        for name, field_name in self.APPLIES.items():
            if wanted.startswith(name):
                return field_name
        return ""

    def as_prompt_block(self, limit: int = 8) -> str:
        """The preferences, in the form the prompt builder wants."""
        facts = self.memory.facts()
        return "\n".join(f"- {fact}" for fact in facts[:limit])

    def describe(self) -> dict:
        return {
            "preferences": {
                fact.key: fact.value for fact in self.memory.store.all_facts()
            },
        }


def _coerce(field_name: str, value: str):
    from jarvis2.config.defaults import VOICE_INDEX

    if field_name == "voice_volume":
        cleaned = "".join(c for c in value if c.isdigit() or c == ".")
        try:
            return max(0.0, min(1.0, float(cleaned) / 100 if float(cleaned) > 1
                                else float(cleaned)))
        except ValueError:
            return 1.0
    if field_name == "voice_index":
        return VOICE_INDEX
    return value
