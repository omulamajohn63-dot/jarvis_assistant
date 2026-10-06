"""Reading a sentence.

Kept apart from the rest because every part of the assistant needs these and
they change for one reason only: the wording people use changes. Pure functions,
no state, no imports beyond the standard library.
"""

from __future__ import annotations

import re

# A leading article, so "the music folder" and "music folder" reach the same
# place.
ARTICLES = ("the ", "my ", "a ", "an ")

# Wording wrapped around a command without changing what it does. Taken off the
# end, so "shut down my computer now" and "shut down" are the same command.
COMMAND_FILLER = (
    "now", "please", "already", "then", "too", "as well",
    "computer", "pc", "laptop", "system", "machine", "desktop",
    "my computer", "this computer", "the computer", "my pc", "this pc",
    "my laptop", "my system",
)

# How someone opens their mouth before a command.
POLITE_PREFIXES = (
    "please ", "can you ", "could you ", "would you ", "hey jarvis ",
)

# Words that only frame a question about the clock or the date, rather than
# naming a subject. "what is the time machine" mentions "time" but also
# "machine", so it is a question about the machine.
QUESTION_FILLER = {
    "what", "whats", "is", "are", "was", "the", "current", "now", "tell",
    "me", "please", "it", "of", "day", "today", "date", "time", "clock",
    "o'clock", "right", "exactly",
}

CLOCK_WORDS = {"time", "clock", "o'clock"}
DATE_WORDS = {"date", "day", "today", "calendar"}

# Words that mean "look this up", for anyone who prefers to be explicit.
LOOKUP_WORDS = ("wikipedia", "wiki")

# Wording wrapped around a topic, stripped before looking it up. Longest first.
QUESTION_PREFIXES = (
    "tell me about", "search for", "look up", "search", "define", "explain",
    "what is", "what are", "what was", "who is", "who was", "who are",
    "where is", "where are", "when did", "when was", "when is",
    "why is", "why are", "why was", "why does", "why do", "why did", "why has",
    "how does", "how do", "how did", "how can", "how to", "how much", "how many",
    "tell me why", "tell me how", "tell me what", "tell me who", "tell me where",
)

# Answers to something Jarvis asked. These are not questions, so they must not
# be sent off to be looked up when no list is waiting for one.
REPLY_WORDS = {
    "yes", "yeah", "yep", "no", "nope", "ok", "okay", "sure", "thanks",
    "thank", "you", "never", "mind", "cancel", "goodbye", "bye",
    "more", "next", "again", "all", "everything", "page", "show",
}


def words_of(text: str) -> set:
    """The whole words in a phrase, lowercased.

    A trailing "'s" is dropped, so "today's date" and "today" are the same word
    to the question helpers.
    """
    found = re.findall(r"[a-z0-9']+", str(text).lower())
    return {
        word[:-2] if word.endswith("'s") else word
        for word in found
    }


def strip_articles(text: str) -> str:
    """Removes a leading article."""
    lowered = text.lower()
    for article in ARTICLES:
        if lowered.startswith(article):
            return text[len(article):].strip()
    return text


def asks_about(text: str, subject_words) -> bool:
    """True when a question is only about the clock or the date.

    The subject word has to be there, and nothing outside the filler words may
    be mentioned alongside it. That is what tells "what is the time" apart from
    "what is the time machine".
    """
    words = words_of(text)
    return bool(words & set(subject_words)) and words <= QUESTION_FILLER


def asks_for_time(text: str) -> bool:
    return asks_about(text, CLOCK_WORDS)


def asks_for_date(text: str) -> bool:
    return asks_about(text, DATE_WORDS)


def mentions_lookup(text: str) -> bool:
    """True when the user named Wikipedia outright."""
    return bool(words_of(text) & set(LOOKUP_WORDS))


# Verbs that name an action rather than a subject. Anything carrying one of these
# is a command even when it is phrased as a question, because "what is the time
# machine playing" is a request to play a file.
ACTION_WORDS = {
    "open", "launch", "start", "run", "play", "pause", "stop", "watch",
    "read", "delete", "remove", "move", "rename", "copy", "close", "type",
    "send", "download", "install", "uninstall", "restart", "shutdown", "sleep",
    "screenshot", "print", "email", "browse", "search",
}


def asks_for_knowledge(text: str) -> bool:
    """True when a phrase is a question that has a subject to look up.

    Two things have to be true: it must be phrased as a question, and something
    must be left over once the question wording is taken off. "hello" is neither,
    and "who is" on its own is the first without the second.
    """
    candidate = str(text).strip()
    if not candidate:
        return False

    found = words_of(candidate)
    if not found:
        return False

    # A command phrased as a question is still a command.
    if found & ACTION_WORDS:
        return False

    lowered = candidate.lower()
    if not (mentions_lookup(candidate)
            or any(lowered.startswith(prefix) for prefix in question_prefixes())
            or candidate.rstrip().endswith("?")):
        return False

    return bool(lookup_topic(candidate))


def is_a_reply(text: str) -> bool:
    """True when a phrase answers Jarvis rather than asking it anything.

    A number or a "yes" on its own is an answer to a list that is not there, and
    looking "1" up on Wikipedia would be nonsense.
    """
    candidate = str(text).strip()
    if candidate.isdigit():
        return True
    words = words_of(candidate)
    return bool(words) and words <= REPLY_WORDS


def question_prefixes() -> tuple:
    """The question words, longest first so "wikipedia" beats "wiki"."""
    return tuple(sorted(
        tuple(QUESTION_PREFIXES) + tuple(LOOKUP_WORDS),
        key=len,
        reverse=True,
    ))


def scaffolding() -> set:
    """Every word that only frames a question rather than naming a topic."""
    words = set(QUESTION_FILLER)
    for phrase in tuple(QUESTION_PREFIXES) + tuple(LOOKUP_WORDS):
        words |= words_of(phrase)
    return words


def strip_one_prefix(text: str) -> str:
    """Removes one leading question word, if there is one to remove.

    Tried longest first, or "wiki" would be chopped off the front of
    "wikipedia" and leave "pedia" behind.
    """
    lowered = text.lower()
    for prefix in question_prefixes():
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    return text.strip()


def lookup_topic(query: str) -> str:
    """Strips the question wording, so "who is X" looks up X.

    Prefixes stack, so "wikipedia what is the time" is unwrapped one layer at a
    time. Unwrapping stops as soon as nothing more comes off, which is what
    protects a topic that happens to start with a question word: without that,
    "what is the time machine" keeps unwrapping "what is" for every pass, since
    the topic still has words left in it.
    """
    text = str(query).strip()

    for _ in range(4):
        remainder = strip_one_prefix(text)
        if not remainder:
            # Nothing is left once the question wording is off, so there is no
            # topic to look up. Returning the original wording instead would send
            # "tell me about" to Wikipedia as though it were a subject.
            return ""
        if remainder == text:
            break
        if not words_of(remainder) - scaffolding():
            break
        text = remainder

    for word in LOOKUP_WORDS:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text, flags=re.IGNORECASE)

    # Naming the site and then the topic is the usual shape, and the preposition
    # in the middle of it is not part of the subject: "wikipedia for mercury"
    # looks up mercury, not "for mercury".
    text = re.sub(r"^\s*(?:for|about|on|of|regarding|re)\s+", "", text,
                  flags=re.IGNORECASE)

    return " ".join(text.split()).strip(" ?.!,;:")


def unwrap_command(text: str) -> str:
    """Takes the opening politeness and the wake word off a command.

    "Hey Jarvis, please open chrome" and "open chrome" are the same instruction.
    Matching the command against the whole sentence instead means the skill only
    answers the one phrasing somebody happened to use.

    Removed repeatedly, because "hey jarvis please open chrome" carries both.
    """
    current = " ".join(str(text).split()).strip().lower()

    shortened = True
    while shortened:
        shortened = False
        for prefix in POLITE_PREFIXES:
            if current.startswith(prefix):
                current = current[len(prefix):].strip(" .?!,")
                shortened = True

    return current


def normalize_command(text: str) -> str:
    """Reduces a command to the bare form that identifies it.

    "Hey Jarvis, please shut down my computer now." and "shut down windows"
    both come out as "shut down". The loop runs until nothing more comes off,
    because the wording overlaps: removing "now" leaves "shut down my computer",
    which loses "computer", which leaves an article that has to go as well.
    """
    current = str(text).strip().lower().strip(" .?!,")

    shortened = True
    while shortened:
        shortened = False

        for prefix in POLITE_PREFIXES:
            if current.startswith(prefix):
                current = current[len(prefix):].strip(" .?!,")
                shortened = True

        for article in ARTICLES:
            if current.startswith(article):
                current = current[len(article):].strip(" .?!,")
                shortened = True
            # A trailing article goes too, or removing a filler first would
            # leave "shut down my" behind, which is not a command anyone said.
            if current.endswith(" " + article.strip()):
                current = current[: -len(article)].strip(" .?!,")
                shortened = True

        for filler in COMMAND_FILLER:
            if current.endswith(" " + filler):
                current = current[: -(len(filler) + 1)].strip(" .?!,")
                shortened = True

    return current


def first_sentences(text: str, count: int) -> str:
    """Keeps only the opening sentences of a passage."""
    parts = re.split(r"(?<=[.!?])\s+", str(text).strip())
    return " ".join(part for part in parts[:count] if part).strip()
