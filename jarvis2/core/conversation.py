"""What the assistant knows about the conversation so far.

Two things live here. The short-term memory is the recent turns, bounded so it
cannot grow without limit and never sent to a provider whole. The session state
is what lets "the previous file" and "the second result" mean something: which
files were really opened, and which numbered list is waiting.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from jarvis2.core.models import Choice, Turn
from jarvis2.logging_utils import get_logger

_log = get_logger("context")


@dataclass
class SessionState:
    """Everything one conversation is holding on to."""

    # Recent turns, oldest first. Bounded by count.
    turns: deque = field(default_factory=lambda: deque(maxlen=12))

    # Files that were really opened, most recent first. Checked against the
    # filesystem when referred to, so a file that has since been moved is not
    # claimed as still open.
    last_opened: list = field(default_factory=list)

    # A numbered list waiting for the user to choose.
    pending_choices: list = field(default_factory=list)
    pending_question: str = ""
    pending_action: str = ""
    # What the list was about, so picking from it still knows the question that
    # produced it. "Mercury" resolves to a planet, a metal or a Roman god, and
    # the entries alone do not say which was asked about.
    pending_topic: str = ""

    # The last article that was read, so "where do I read more?" has an answer.
    last_source: dict | None = None

    # The topic of the last thing discussed, for "tell me more".
    last_topic: str = ""

    def record(self, turn: Turn) -> None:
        self.turns.append(turn)
        if turn.opened:
            self.last_opened = list(turn.opened)
        if turn.sources:
            self.last_source = turn.sources[-1]
        if turn.request:
            self.last_topic = turn.request

    # ------------------------------------------------------------------
    def remember_choices(self, choices: list, question: str,
                         action: str, topic: str = "") -> None:
        self.pending_choices = list(choices)
        self.pending_question = question
        self.pending_action = action
        self.pending_topic = topic

    def take_choices(self) -> list:
        choices = self.pending_choices
        self.pending_choices = []
        self.pending_question = ""
        self.pending_action = ""
        self.pending_topic = ""
        return choices

    def has_choices(self) -> bool:
        return bool(self.pending_choices)

    # ------------------------------------------------------------------
    def history(self, limit: int | None = None) -> list:
        turns = list(self.turns)
        return turns[-limit:] if limit else turns

    def find_last_path(self, matching=None) -> str | None:
        """The most recent path that is still on disk and is worth referring to.

        The filesystem decides whether it is still there, so "what was the file
        I just opened?" is answered from something real. A protected directory
        or an executable is refused as well: neither is ever what a person means
        by "the file I just opened", and a reference that resolved to one would
        be worse than no answer at all.
        """
        from jarvis2.safety import paths as path_safety

        for path in self.last_opened:
            if matching and not matching(path):
                continue
            if path_safety.is_protected(path) or path_safety.looks_executable(path):
                continue
            if Path(path).exists():
                return path
        return None

    def clear(self) -> None:
        self.turns.clear()
        self.last_opened.clear()
        self.pending_choices.clear()
        self.pending_question = ""
        self.pending_action = ""
        self.pending_topic = ""
        self.last_source = None
        self.last_topic = ""

    def snapshot(self) -> dict:
        return {
            "turns": len(self.turns),
            "lastOpened": list(self.last_opened),
            "pending": len(self.pending_choices),
            "question": self.pending_question,
            "pendingAction": self.pending_action,
            "pendingTopic": self.pending_topic,
            "lastSource": self.last_source,
            "lastTopic": self.last_topic,
        }


# Words that point back at something already mentioned. Each one is only
# resolved when there is exactly one thing it could mean.
REFERENCES = {
    "it": "last",
    "that": "last",
    "that one": "choice",
    "this": "last",
    "this one": "choice",
    "the same": "last",
    "the previous one": "last",
    "the previous file": "last_path",
    "the last one": "choice",
    "the last file": "last_path",
    "the first one": "ordinal",
    "the second one": "ordinal",
    "the third one": "ordinal",
    "the first": "ordinal",
    "the second": "ordinal",
    "the third": "ordinal",
    "he": "person",
    "she": "person",
    "him": "person",
    "her": "person",
    "they": "person",
}

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    # Whose position depends on how many there are, which is why they are not
    # in the plain numbering above.
    "last": -1, "final": -1,
}

# Wording carried by a reference rather than by the reference itself.
FILLER = {
    "the", "a", "an", "one", "ones", "file", "files", "result", "results",
    "please", "show", "me", "open", "read", "number", "no", "that", "this",
    "again", "and",
}


def words_of(text: str) -> list:
    import re

    return re.findall(r"[a-z0-9']+", text.lower())


class Conversation:
    """Bounded history plus the resolution of what a follow-up refers to."""

    def __init__(self, max_turns: int = 12):
        self.max_turns = max_turns
        self.state = SessionState(turns=deque(maxlen=max_turns))

    # ------------------------------------------------------------------
    def record(self, request: str, reply: str, skill: str = "",
               opened: list = None, sources: list = None) -> Turn:
        turn = Turn(
            request=request, reply=reply, skill=skill or None,
            opened=list(opened or []), sources=list(sources or []),
        )
        self.state.record(turn)
        return turn

    def history(self, limit: int | None = None) -> list:
        return self.state.history(limit)

    def clear(self) -> None:
        self.state.clear()

    # ------------------------------------------------------------------
    def resolve_reference(self, text: str) -> str | None:
        """Turns "the previous file" into a path, when there is one.

        Returns None when the words carry no reference, or when what they point
        at cannot be pinned down. Guessing here would open the wrong file, so an
        ambiguous reference is left to the user.
        """
        words = words_of(text)
        if not words:
            return None

        # Most specific reference wins when several appear. Checked over the
        # phrases rather than over single words, because several of the
        # references are phrases and none of their words appear alone in them.
        for length in (3, 2, 1):
            for start in range(len(words) - length + 1):
                phrase = " ".join(words[start:start + length])
                if phrase not in REFERENCES:
                    continue
                kind = REFERENCES[phrase]
                if kind == "last_path":
                    path = self.state.find_last_path()
                    if path:
                        return path
                return None

        return None

    def resolve_ordinal(self, text: str) -> int | None:
        """Turns "the second one" into a position in the waiting list."""
        words = [word for word in words_of(text) if word not in FILLER]
        choices = self.state.pending_choices

        for word in words:
            if word not in ORDINALS:
                continue
            index = ORDINALS[word]
            if index == -1:
                # Whose position depends on how many there are.
                return len(choices) or None
            return index if 0 < index <= len(choices) else None

        import re

        numbered = re.search(r"\b(\d+)\s*(?:st|nd|rd|th)\b", text.lower())
        if numbered:
            index = int(numbered.group(1))
            return index if 0 < index <= len(choices) else None
        return None

    def resolve_choice(self, text: str) -> Choice | None:
        """Turns a number or a word into one entry of the waiting list."""
        choices = self.state.pending_choices
        if not choices:
            return None

        stripped = text.strip().lower().strip(" .?!,")
        if stripped.isdigit():
            index = int(stripped)
            return choices[index - 1] if 0 < index <= len(choices) else None

        index = self.resolve_ordinal(text)
        if index is not None:
            return choices[index - 1]
        return None

    def resolve_subject(self, text: str) -> str | None:
        """Turns "he" or "that" into what was last being talked about.

        Only used for a question, never for an instruction to act on, because a
        pronoun naming a person cannot safely stand in for a file path.
        """
        words = set(words_of(text))
        if not words & {"he", "she", "him", "her", "they", "it", "that"}:
            return None

        turns = self.history()
        for turn in reversed(turns):
            if turn.request:
                return turn.request
        return self.state.last_topic or None

    def last_path(self) -> str | None:
        return self.state.find_last_path()

    def last_choice(self) -> Choice | None:
        choices = self.state.pending_choices
        return choices[-1] if choices else None

    def remember_choices(self, choices: list, question: str,
                         action: str, topic: str = "") -> None:
        self.state.remember_choices(choices, question, action, topic)

    def has_choices(self) -> bool:
        return self.state.has_choices()

    def take_choices(self) -> list:
        return self.state.take_choices()

    # ------------------------------------------------------------------
    def memory_block(self, max_chars: int = 2000) -> str:
        """The conversation as a block of text, for a prompt or a log.

        Bounded on purpose. An unbounded history is slow, expensive, and mostly
        filler.
        """
        parts = []
        for turn in self.history():
            if turn.request:
                parts.append(f"User: {turn.request}")
            if turn.reply:
                parts.append(f"{turn.request and '' or ''}Jarvis: {turn.reply}")

        block = "\n".join(parts)
        if len(block) > max_chars:
            block = block[-max_chars:]
        return block

    def snapshot(self) -> dict:
        state = self.state.snapshot()
        state["age"] = round(time.time() - (self.state.turns[-1].at
                                            if self.state.turns else time.time()), 1)
        return state
