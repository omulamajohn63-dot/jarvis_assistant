"""Answering questions from Wikipedia.

The skill's own work is deciding what the question means and what to say. The
reading is in jarvis2.knowledge.wiki.

An ambiguous name is offered as a numbered list rather than guessed at, which is
the same list every other search uses, so "2" picks one without any extra
handling anywhere.
"""

from __future__ import annotations

from jarvis2.core.models import Choice, Request, SkillResult
from jarvis2.files import text as words
from jarvis2.knowledge import wiki
from jarvis2.logging_utils import get_logger
from jarvis2.skills.base import Skill, SkillContext

_log = get_logger("skills.knowledge")


class KnowledgeSkill(Skill):
    name = "knowledge"
    description = (
        "Look a question up on Wikipedia and read the article out, or offer the "
        "articles a name could mean when it means several."
    )
    actions = ("lookup_wikipedia", "search_web")
    keywords = ("wikipedia", "wiki", "who is", "what is", "tell me about",
                "who was", "when was", "when did", "where is", "explain",
                "define")

    def __init__(self, wikipedia_client=None):
        self._wikipedia = wikipedia_client

    def client(self, context: SkillContext):
        if self._wikipedia is not None:
            return self._wikipedia
        if context.session is not None:
            reader = getattr(context.session, "wikipedia", None)
            if reader is not None:
                return reader
        return wiki.Wikipedia()

    # ------------------------------------------------------------------
    async def can_handle(self, request: Request) -> float:
        text = request.normalized
        if not text:
            return 0.0

        # Naming Wikipedia outright is unambiguous, and beats a model: the user
        # asked for that site by name.
        if words.mentions_lookup(text):
            return 0.9

        # A question the lookup could answer, but scored under the router's
        # threshold on purpose. A configured model answers questions better, and
        # this skill is the route taken when there is no model or the model
        # cannot be reached.
        if not words.asks_for_knowledge(text):
            return 0.0

        return 0.4

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        """Looks the question up, or refuses before touching the network.

        This is reached by the fallback route as well as by the router, and the
        fallback route carries whatever no skill claimed. Searching Wikipedia
        for "how do i restart windows safely" would answer a question about the
        machine with an article about restarting, so a request with no subject to
        look up is turned away here instead.
        """
        if not words.asks_for_knowledge(request.normalized):
            return SkillResult(
                succeeded=False,
                text="I do not know how to do that yet.",
            )

        answer = await context.run_blocking(
            self.client(context).resolve, request.text
        )
        return self._to_result(answer)

    def _to_result(self, answer) -> SkillResult:
        """Turns what the lookup produced into something to show.

        The numbered list is built here and nowhere else, so a list of articles
        looks the same as a list of files and the page has one thing to draw.
        """
        if answer.ambiguous:
            choices = [
                Choice(number=index, label=title, payload=title)
                for index, title in enumerate(answer.candidates, 1)
            ]
            return SkillResult(
                succeeded=True,
                text=(f"{answer.topic} could mean several things. "
                      "Which one?"),
                choices=choices,
                question=f"{len(choices)} articles could match {answer.topic}",
                action="lookup",
                topic=answer.topic,
            )

        if answer.resolved:
            article = answer.article
            # The title first, so it is always clear what is being heard.
            return SkillResult(
                succeeded=True,
                text=f"{article.title}. {article.summary}",
                sources=[{"title": article.title, "url": article.url,
                          "kind": "wikipedia"}],
                actions=[{"action": "lookup", "target": article.title}],
                metadata={"article": article.as_dict()},
            )

        return SkillResult(succeeded=False, text=answer.reason)

    # ------------------------------------------------------------------
    async def read_title(self, title: str, topic: str,
                         context: SkillContext) -> SkillResult:
        """Reads one article whose title is already exact."""
        answer = await context.run_blocking(
            self.client(context).read_title, title, topic
        )
        return self._to_result(answer)


def progress(text: str) -> str:
    """What to show while a slow lookup is running."""
    return f"Searching Wikipedia for {text.strip('?.!')}..."
