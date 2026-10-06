"""Small things worth having: jokes, and a way to test the assistant works."""

from __future__ import annotations

from jarvis2.core.models import Request, SkillResult
from jarvis2.skills.base import Skill, SkillContext

# Told when pyjokes is not installed, so a missing package is a sentence rather
# than a traceback.
NO_JOKES = (
    "I would tell you a joke, but the joke library is not installed on this "
    "computer."
)


class JokeSkill(Skill):
    name = "jokes"
    description = "Tell a joke."
    actions = ("tell_joke",)
    keywords = ("joke", "funny", "make me laugh", "something funny")

    async def can_handle(self, request: Request) -> float:
        return 0.95 if any(word in request.normalized
                           for word in self.keywords) else 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        import asyncio

        def tell():
            import pyjokes

            return pyjokes.get_joke()

        try:
            joke = await asyncio.to_thread(tell)
        except Exception:
            # An absent or broken library is not the user's problem.
            return SkillResult(succeeded=False, text=NO_JOKES)

        return SkillResult(succeeded=True, text=str(joke).strip())


class SelfTestSkill(Skill):
    name = "selftest"
    description = "Check that the assistant's own parts are working."
    actions = ("list_skills",)
    keywords = ("self test", "selftest", "diagnose", "are you working",
                "health check", "debug")

    async def can_handle(self, request: Request) -> float:
        return 0.9 if any(word in request.normalized
                          for word in self.keywords) else 0.0

    async def execute(self, request: Request,
                      context: SkillContext) -> SkillResult:
        parts = {
            "skills": len(context.session.registry) if context.session else 0,
            "wikipedia": context.wikipedia is not None,
            "provider": getattr(context.provider, "name", None) or "none",
            "memory": bool(context.memory),
            "voice": context.settings.voice_enabled,
            "history": (
                len(context.session.conversation.history())
                if context.session else 0
            ),
        }
        missing = [
            name for name, present in (
                ("a knowledge provider", parts["provider"] != "none"),
                ("Wikipedia access", parts["wikipedia"]),
            )
            if not present
        ]

        summary = (
            f"{parts['skills']} skills, "
            f"{'a model is' if parts['provider'] != 'none' else 'no model'}, "
            f"memory {'on' if parts['memory'] else 'off'}."
        )
        if missing:
            summary += " Working without " + " and ".join(missing) + "."

        return SkillResult(succeeded=True, text=summary, data=parts)
