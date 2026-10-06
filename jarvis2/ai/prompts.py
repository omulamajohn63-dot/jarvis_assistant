"""Building the prompts.

The model is told what the skills are and what it may not do, and is given the
tool definitions generated from the registry rather than a description written
by hand. That way a skill cannot be advertised to the model in a way the code
does not support.
"""

from __future__ import annotations

import json

from jarvis2.ai.provider import user

# What Jarvis is, every time.
IDENTITY = """\
You are {name}, a personal assistant running on the user's own Windows computer.

You can see the user's screen context indirectly: you know what has just been
opened and what was found, but you cannot see anything you have not been told.
Never claim you have done something that has not been confirmed back to you as
having succeeded.

You are talking to {addressee}. Keep replies short enough to be spoken aloud
unless the user asked for detail.
"""

# The rules the model works under. Kept separate from the identity because
# these are the ones that must not be softened.
RULES = """\
Rules you do not break:

- You choose tools. You never run anything yourself and never write code.
- Every tool call is checked by this program before it runs. If you ask for
  something risky the user will be asked to confirm it, and your request may be
  refused. Do not try to work around that.
- If a tool reports a failure, say what failed. Do not claim an action happened
  because you intended it to.
- If you are unsure what the user means, ask. A wrong guess that opens the wrong
  file is worse than a question.
- Answer from what you know. When a tool gives you current information, use it
  and say where it came from.
"""

# What the assistant is not allowed to do, stated plainly so the model does not
# spend turns proposing them.
LIMITS = """\
There is no tool for running shell commands, and asking for one will be refused.
There is no tool for deleting files without confirmation. There is no tool for
reading anything outside the user's own folders.
"""

TOOL_INSTRUCTIONS = """\
When you want to do something on this computer, call a tool. When you simply
need to talk or answer, reply in plain text with no tool call.
"""


def tool_for_skill(skill) -> dict:
    """A JSON schema description of one skill, for a provider's tools list.

    Generated from the skill so the model is never told about a capability the
    code does not have.
    """
    parameters = _schema_for(skill)

    return {
        "type": "function",
        "function": {
            "name": skill.name,
            "description": skill.description or skill.name,
            "parameters": parameters,
        },
    }


# What each skill needs, kept beside the schema so the two cannot disagree.
_ARGUMENTS = {
    "files": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for"},
            "search_drives": {
                "type": "boolean",
                "description": "Also search every other drive",
            },
        },
        "required": ["query"],
    },
    "documents": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The document's name"},
            "read": {
                "type": "boolean",
                "description": "Read it aloud instead of opening it",
            },
        },
        "required": ["query"],
    },
    "media": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The song or video"},
        },
        "required": ["query"],
    },
    "apps": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The application's name"},
        },
        "required": ["name"],
    },
    "browser": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Address to open"},
            "query": {"type": "string", "description": "What to search for"},
        },
    },
    "system": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["time", "date", "status", "volume", "mute"],
            },
        },
    },
    "screenshot": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Filename to save as"},
        },
    },
    "conversation": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Subject to discuss"},
        },
    },
}


def _schema_for(skill) -> dict:
    """The schema for a skill, keyed on the family it belongs to."""
    family = skill.name.split("_")[0]
    schema = _ARGUMENTS.get(family)
    if schema:
        return json.loads(json.dumps(schema))

    return {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def build_system_prompt(settings, skills, memories: list | None = None,
                        extra: str = "") -> str:
    """The system message, built from the skills that are actually registered."""
    addressee = (
        f"{settings.user_name}" if settings.user_name else "the user"
    )
    skill_list = "\n".join(
        f"- {skill.name}: {skill.description}"
        for skill in skills
        if skill.description
    )

    parts = [
        IDENTITY.format(name=settings.assistant_name, addressee=addressee),
        LIMITS,
        RULES,
        TOOL_INSTRUCTIONS,
        f"Tools available to you:\n{skill_list}" if skill_list else "",
    ]

    if memories:
        listed = "\n".join(f"- {item}" for item in memories)
        parts.append(
            "Things you remember about this user, which you may use but may "
            f"not contradict:\n{listed}"
        )

    if extra:
        parts.append(extra)

    return "\n\n".join(part for part in parts if part)


def build_conversation(history, question: str, memories: list | None = None,
                       extra: str = "") -> list:
    """The message list, bounded by the settings before it is ever sent.

    A provider is never handed an unbounded history: the cost and the delay are
    both real, and the assistant only needs enough to resolve "it" and "when was
    he born".
    """
    messages = []
    for turn in history:
        if turn.request:
            messages.append(user(turn.request))
        if turn.reply:
            messages.append(
                {"role": "assistant", "content": turn.reply}
            )
    messages.append(user(question))
    return messages


def bound_messages(messages: list, max_turns: int, max_chars: int) -> list:
    """Keeps the most recent turns within a budget.

    Trims from the front, because the recent turns are the ones that resolve
    references. A single oversized message is left alone: cutting it would lose
    the question that was actually asked.
    """
    if max_turns > 0 and len(messages) > max_turns * 2:
        messages = messages[-max_turns * 2:]

    total = sum(len(str(entry.get("content") or "")) for entry in messages)
    while total > max_chars and len(messages) > 2:
        dropped = messages.pop(0)
        total -= len(str(dropped.get("content") or ""))

    return messages
