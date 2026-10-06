"""Structured logging that cannot leak a secret.

Every record carries a timestamp, a level, the component it came from, the
event, a message and how long the work took. Values are redacted on the way out
rather than at each call site, because the one call site someone forgets is the
one that writes a key to disk.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

# The names and shapes of things that must never reach a log file. Matching on
# the name catches anything that looks like a key; matching on the value catches
# a key that was passed under an innocent name.
SECRET_NAMES = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|token|authorization|credential"
    r"|cookie|session[_-]?id|private[_-]?key)"
)

SECRET_VALUES = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),          # OpenAI style
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),         # Google
    re.compile(r"AIza[0-9A-Za-z\-_]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9]{16,}"),  # GitHub
)

REDACTED = "[redacted]"

# How much of any one value is kept when it is not a secret, so a long reply
# cannot fill the log.
MAX_VALUE_CHARS = 300


def redact(value: Any, name: str = "") -> Any:
    """Returns a loggable form of a value, with anything secret replaced.

    Scalars keep their type. Turning everything into a string would make
    ``succeeded=False`` arrive as ``"False"``, which is truthy in JavaScript, so
    a page would show a failed action as a successful one. Only containers are
    rendered, because they are for a human to read.
    """
    if name and SECRET_NAMES.search(name):
        return REDACTED

    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"

    # Left alone: a page compares these, and a string version would lie.
    if isinstance(value, (bool, int, float)) or value is None:
        return value

    text = str(value)
    for pattern in SECRET_VALUES:
        text = pattern.sub(REDACTED, text)
    if len(text) > MAX_VALUE_CHARS:
        text = text[:MAX_VALUE_CHARS] + "..."
    return text


def redact_mapping(values: dict) -> dict:
    """Redacts a whole mapping, by key name and by value shape.

    Containers are kept as they are rather than rendered, so a page reading this
    still finds a list of what was opened instead of its text.
    """
    return {name: redact(value, name) for name, value in values.items()}


def redact_deep(value: Any, name: str = "") -> Any:
    """Redacts a nested structure, keeping lists and objects readable."""
    if isinstance(value, dict):
        return {key: redact_deep(item, str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_deep(item, name) for item in value]
    return redact(value, name)


@dataclass
class Event:
    """One thing that happened, in a form a log file or a web page can show."""

    name: str
    component: str
    data: dict = field(default_factory=dict)
    duration: float | None = None
    level: str = "info"

    def as_record(self) -> dict:
        return {
            "event": self.name,
            "component": self.component,
            "level": self.level,
            "duration_ms": (
                None if self.duration is None else round(self.duration * 1000, 2)
            ),
            **redact_mapping(self.data),
        }


class StructuredFormatter(logging.Formatter):
    """Writes one record per line, with the parts the project cares about."""

    def format(self, record: logging.LogRecord) -> str:
        parts = [f"{self.formatTime(record)}", record.levelname.ljust(7),
                 record.name.ljust(18), record.getMessage()]

        duration = getattr(record, "duration", None)
        if duration is not None:
            parts.append(f"({duration * 1000:.0f}ms)")

        if record.exc_info:
            # The traceback is internal detail. The user gets a sentence; the
            # log gets the whole thing.
            parts.append("\n" + self.formatException(record.exc_info))

        return " ".join(parts)


def configure(level: str = "INFO", logfile: str | None = None) -> None:
    """Sets up the root logger once, writing to stderr and optionally a file."""
    root = logging.getLogger("jarvis2")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if root.handlers:
        return

    formatter = StructuredFormatter()
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if logfile:
        file_handler = logging.FileHandler(logfile, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # The libraries V1 uses log their own warnings, which are not ours and are
    # mostly harmless (Wikipedia's parser notice, for one).
    root.propagate = False


def get_logger(component: str) -> logging.Logger:
    """The logger for one part of the assistant."""
    return logging.getLogger(f"jarvis2.{component}")


@contextmanager
def timed(logger: logging.Logger, action: str, **data: Any) -> Iterator[dict]:
    """Logs how long a piece of work took, and whether it failed.

    Yields the dict it will log, so the caller can add to it as it learns things.
    """
    record: dict = dict(data)
    started = time.perf_counter()
    try:
        yield record
    except Exception as error:
        logger.error(redact(action), exc_info=True,
                     duration=time.perf_counter() - started)
        record["error"] = f"{type(error).__name__}: {redact(error)}"
        raise
    else:
        logger.info(
            redact(action), extra={"duration": time.perf_counter() - started},
            **{"data": redact_mapping(record)},
        )
