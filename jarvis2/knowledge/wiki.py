"""Looking a topic up on Wikipedia.

The awkward part of this is not the reading, it is deciding what the topic
*is*. A name like "mercury" means several things, and a search for the whole
sentence returns nonsense: "how do i restart windows safely" comes back with
articles about blue screens and Windows XP. So the question wording is removed
first, and a result that does not match what was asked about is rejected rather
than read out.

The HTTP calls use a session of this object's own. The Wikipedia library calls
requests.get with no timeout, and the only way to give it one used to be to wrap
the global function, which is not something two lookups can safely do at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

from jarvis2.files.text import first_sentences, lookup_topic, words_of
from jarvis2.logging_utils import get_logger

_log = get_logger("knowledge.wiki")

# Wikimedia rejects the library's default User-Agent with HTTP 429.
USER_AGENT = (
    "JarvisDesktopAssistant/2.0 "
    "(https://github.com/omulamajohn63-dot/jarvis_assistant)"
)

BASE_URL = "https://en.wikipedia.org/w/api.php"

# Seconds to wait before giving up. The library sets no timeout of its own, so
# one slow reply would otherwise leave the assistant waiting for ever.
TIMEOUT = 10

# How many alternative articles to offer when a topic means several things.
CHOICES = 5

# How many sentences of an article to read out.
SENTENCES = 2

# Words that only frame a question rather than name a subject.
FRAMING = {
    "what", "whats", "is", "are", "was", "the", "current", "now", "tell",
    "me", "please", "it", "of", "day", "today", "date", "time", "clock",
    "o'clock", "right", "exactly", "how", "do", "i", "to", "you", "can",
    "my", "a", "an", "in", "on", "for", "with", "why", "who", "when",
    "where", "which", "if", "not", "s",
}


@dataclass
class Article:
    """One article, and where it came from."""

    topic: str
    title: str
    summary: str
    url: str

    def as_dict(self) -> dict:
        return {
            "topic": self.topic,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
        }


@dataclass
class Answer:
    """What a lookup produced: an article, a list of candidates, or a reason."""

    article: Article | None = None
    candidates: list = field(default_factory=list)
    topic: str = ""
    # Why there is no article, in words fit to say out loud.
    reason: str = ""
    # True when the site could not be reached, which is different from the
    # topic not being there.
    offline: bool = False

    @property
    def resolved(self) -> bool:
        return self.article is not None

    @property
    def ambiguous(self) -> bool:
        return bool(self.candidates)


# The opening words of a Wikipedia disambiguation page. They say the title is a
# list of meanings rather than an article, which is what has to be detected
# before the text is read aloud.
HATNOTE_STARTS = (
    "may refer to", "may also refer to", "refers to the following",
    "refers to the", "commonly refers to", "usually refers to",
    "is a disambiguation", "is a general disambiguation",
)


def is_hatnote(text: str) -> bool:
    """True when an article body is really a disambiguation page."""
    opening = " ".join(str(text or "").lower().split())[:400]
    return any(phrase in opening for phrase in HATNOTE_STARTS)


class Offline(Exception):
    """Raised when Wikipedia cannot be reached at all."""


class Wikipedia:
    """Reads and resolves articles."""

    def __init__(self, timeout: int = TIMEOUT, session=None, sentences: int = SENTENCES):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.sentences = sentences

    # ------------------------------------------------------------------
    def _request(self, params: dict) -> dict:
        """One API call, with a timeout and a User-Agent that is accepted."""
        params = {**params, "format": "json"}
        headers = {"User-Agent": USER_AGENT}
        try:
            response = self.session.get(
                BASE_URL, params=params, headers=headers, timeout=self.timeout,
            )
        except Exception as error:
            raise Offline(f"could not reach Wikipedia: {error}") from error

        if response.status_code == 429:
            raise Offline("Wikipedia is rate limiting")
        if response.status_code >= 400:
            raise Offline(f"Wikipedia answered {response.status_code}")

        try:
            return response.json()
        except ValueError as error:
            raise Offline("Wikipedia's reply was not JSON") from error

    # ------------------------------------------------------------------
    def search(self, topic: str, limit: int = CHOICES * 2) -> list:
        """Article titles Wikipedia ranks for a topic."""
        try:
            data = self._request({
                "action": "query", "list": "search", "srsearch": topic,
                "srlimit": limit,
            })
        except Offline:
            raise

        hits = (data.get("query") or {}).get("search") or []
        return [
            hit["title"] for hit in hits
            if "disambiguation" not in str(hit.get("title", "")).lower()
        ]

    def extract(self, title: str) -> str:
        """A summary of one article, given its exact title.

        auto_suggest is turned off deliberately. Left on, the library mangles
        the title it was handed, turning "Mount Everest" into "mount everes" and
        then reporting that no such page exists. By this point the title has
        already been found and checked, so there is nothing left to suggest.
        """
        data = self._request({
            "action": "query", "prop": "extracts",
            "exintro": 1, "explaintext": 1, "redirects": 1, "titles": title,
        })
        pages = (data.get("query") or {}).get("pages") or {}
        for page in pages.values():
            if "extract" in page:
                return str(page["extract"])
        raise KeyError(title)

    def url_for(self, title: str) -> str:
        return f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"

    def _hatnote_titles(self, title: str) -> list:
        """The meanings listed on a disambiguation page, in the page's order.

        Read from the page itself so the offered choices are the ones Wikipedia
        actually wrote there, rather than whatever else happened to rank for the
        same word.
        """
        try:
            data = self._request({
                "action": "query", "prop": "links", "titles": title,
                "pllimit": "max",
            })
        except Offline:
            return []

        pages = (data.get("query") or {}).get("pages") or {}
        for page in pages.values():
            titles = [
                link["title"] for link in (page.get("links") or [])
                if not link["title"].lower().startswith(
                    ("category:", "template:", "wikipedia:", "help:", "file:",
                     "portal:")
                )
            ]
            if titles:
                return titles
        return []

    # ------------------------------------------------------------------
    def title_matches(self, topic: str, title: str) -> bool:
        """True when an article title really is about the topic asked for.

        Wikipedia's ranking is trusted, not its suggestions, and the result is
        checked. Without this, asking about one person can be answered with
        another whose name merely ends the same way.
        """
        wanted = words_of(topic) - FRAMING
        if not wanted:
            return True
        return any(
            word in other or other in word
            for word in wanted
            for other in words_of(title)
        )

    # ------------------------------------------------------------------
    def resolve(self, query: str) -> Answer:
        """An article for a question, or the choices when it means several things."""
        topic = lookup_topic(query)

        if not topic:
            return Answer(
                topic=query, reason="Tell me what to look up, for example what "
                "is python.",
            )

        try:
            titles = self.search(topic)
        except Offline:
            return Answer(topic=topic, offline=True,
                          reason="I could not reach Wikipedia. Check your "
                                 "internet connection.")

        if not titles:
            return Answer(topic=topic, reason=f"I could not find {topic} on "
                                               "Wikipedia.")

        best = titles[0]
        if self.title_matches(topic, best):
            return self._article(topic, best, titles)

        # Nothing near the top of the ranking is about what was asked, so the
        # whole set is offered rather than picking one that is plainly wrong.
        return Answer(topic=topic, candidates=titles[:CHOICES])

    def _article(self, topic: str, title: str, alternatives=None) -> Answer:
        try:
            text = self.extract(title)
        except Offline:
            return Answer(topic=topic, offline=True,
                          reason="I could not reach Wikipedia. Check your "
                                 "internet connection.")
        except KeyError:
            return Answer(topic=topic, reason=f"I could not read the article "
                                               f"on {title}.")

        # A disambiguation page opens with "X may refer to..." and is not an
        # article about X. Reading it aloud answers the question with a list of
        # other questions, so the meanings are offered instead and the user
        # picks, which is the whole point of asking.
        if is_hatnote(text):
            candidates = [other for other in (alternatives or [])
                          if other.lower() != title.lower()]
            if not candidates:
                candidates = self._hatnote_titles(title)
            if candidates:
                return Answer(topic=topic, candidates=candidates[:CHOICES])

        summary = " ".join(first_sentences(text, self.sentences).split())
        if not summary:
            return Answer(topic=topic, reason=f"The article on {title} has no "
                                               "text to read.")

        # The title is read out before the text, so it is always clear which
        # article the words came from.
        return Answer(
            topic=topic,
            article=Article(topic=topic, title=title, summary=summary,
                            url=self.url_for(title)),
        )

    def read_title(self, title: str, topic: str = "") -> Answer:
        """Reads one article whose title is already exact."""
        return self._article(topic or title, title)


def is_a_question(text: str) -> bool:
    """True when a message is a question rather than a command.

    Used to decide whether an unrecognised request should be looked up. A
    command that no skill claimed is far more likely to be something Jarvis can
    do, so it is not silently turned into a search.
    """
    words = words_of(text)
    if not words:
        return False
    if words & {"open", "launch", "start", "run", "play", "watch", "read",
                "screenshot", "delete", "move", "rename", "shutdown",
                "restart", "exit"}:
        return False
    return True
