"""Choosing what handles a request.

The order matters and is the whole design:

1. An answer to something already asked. A number or a "yes" belongs to the
   list or the question that is waiting, and must not be read as a new command.
2. A skill, chosen by how well it fits.
3. The AI layer, when one is configured and nothing matched.
4. The V1 assistant, which is the fallback that makes every V1 command work.

Each step is a fallback to the one before it failed, so an unreachable model
never means a broken command, and a broken skill never means silence.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis2.core.models import Request
from jarvis2.logging_utils import get_logger

_log = get_logger("router")


@dataclass
class Route:
    """What the router decided, and why."""

    #: "choice", "skill", "ai" or "knowledge"
    kind: str
    name: str = ""
    score: float = 0.0
    reason: str = ""


class Router:
    """Picks the route for a request."""

    def __init__(self, registry, conversation, provider=None):
        self.registry = registry
        self.conversation = conversation
        self.provider = provider

    async def choose(self, request: Request) -> Route:
        """Which route, decided without running anything."""
        text = request.normalized

        if not text:
            return Route("conversation", reason="nothing was said")

        # An answer to something already asked comes first, or a "2" typed after
        # a list would be read as a command about the number two.
        if self.conversation.has_choices() and self._is_answer(text):
            return Route("choice", reason="answering a waiting list")

        candidates = await self.registry.candidates(request)
        best = candidates[0] if candidates else None

        if best is not None and best.score >= 0.5:
            return Route("skill", best.name, best.score,
                         reason=f"fitted by {best.name}")

        if self.provider is not None:
            return Route("ai", reason="no skill matched and a model is configured")

        return Route("knowledge", reason="no skill matched, so look it up")

    def _is_answer(self, text: str) -> bool:
        """True when the words answer a waiting question rather than command.

        Only words that actually pick something out. Treating every phrase with
        no verb as an answer would swallow the next real command after any list
        is shown, which is how one ambiguous lookup could break the rest of the
        session.
        """
        stripped = text.strip().strip(" .?!,")
        if not stripped:
            return False

        if self.conversation.resolve_choice(stripped) is not None:
            return True

        return stripped.lower() in {
            "yes", "yeah", "yep", "ok", "okay", "sure", "cancel", "more",
            "next", "no", "nope", "never mind", "go ahead", "do it",
            "no thanks", "neither",
        }

    def describe(self) -> dict:
        return {
            "skills": self.registry.names,
            "hasProvider": self.provider is not None,
        }
