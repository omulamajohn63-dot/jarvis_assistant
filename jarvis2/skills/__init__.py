"""The skills Jarvis ships with.

Registration is explicit, in one function, rather than by scanning the package
for subclasses. A list you can read is worth more than the convenience of
discovery, and it is the place a new skill becomes available to the model.
"""

from __future__ import annotations

from jarvis2.skills.apps import (
    ApplicationSkill,
    BrowserSkill,
    ScreenshotSkill,
)
from jarvis2.skills.base import Skill, SkillContext
from jarvis2.skills.files import DocumentSkill, FolderSkill, MediaSkill
from jarvis2.skills.knowledge import KnowledgeSkill
from jarvis2.skills.misc import JokeSkill, SelfTestSkill
from jarvis2.skills.registry import SkillRegistry
from jarvis2.skills.system import (
    ClockSkill,
    ExitSkill,
    ModeSkill,
    PowerSkill,
    SpeakerSkill,
    StatusSkill,
)


def build_default_registry(permissions=None, wikipedia=None) -> SkillRegistry:
    """Every skill this installation has, in the order they are offered.

    Order matters only as a tiebreak: the router scores by fit, and these are
    listed so that the more specific skills are considered before the broader
    ones when two score the same.
    """
    return SkillRegistry(
        [
            PowerSkill(),
            ExitSkill(),
            ClockSkill(),
            JokeSkill(),
            ScreenshotSkill(),
            BrowserSkill(),
            ApplicationSkill(),
            DocumentSkill(),
            MediaSkill(),
            FolderSkill(),
            SpeakerSkill(),
            ModeSkill(),
            ConversationSkill(),
            StatusSkill(),
            SelfTestSkill(),
            KnowledgeSkill(wikipedia_client=wikipedia),
        ],
        permissions=permissions,
    )


# Imported last so that the modules above can be read without this one pulling
# the whole registry in behind them.
from jarvis2.skills.conversation import ConversationSkill  # noqa: E402

__all__ = [
    "ApplicationSkill",
    "BrowserSkill",
    "ClockSkill",
    "ConversationSkill",
    "DocumentSkill",
    "ExitSkill",
    "FolderSkill",
    "JokeSkill",
    "KnowledgeSkill",
    "ModeSkill",
    "MediaSkill",
    "PowerSkill",
    "ScreenshotSkill",
    "SelfTestSkill",
    "Skill",
    "SkillContext",
    "SkillRegistry",
    "SpeakerSkill",
    "StatusSkill",
    "build_default_registry",
]
