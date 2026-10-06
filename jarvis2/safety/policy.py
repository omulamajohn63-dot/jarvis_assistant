"""How risky an action is, and what has to happen before it runs.

The rule the whole project rests on: a language model may suggest an action, and
nothing else. Every path from a suggestion to the filesystem goes through
classify, then validate, then confirm if needed, then execute. Nothing skips a
step, and no caller can ask for a lower risk than the action actually carries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Risk(IntEnum):
    """Ordered, so "at least this risky" is a comparison rather than a set test."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Action:
    """Something that can be done, and how dangerous it is."""

    name: str
    risk: Risk
    description: str = ""
    # What the action touches, so a decision can name it: "C:\\Users\\me\\cv.pdf".
    target: str = ""
    # Whether it can be undone. Deleting a file in the Recycle Bin can; a
    # shutdown cannot, which is why one asks and the other might not.
    reversible: bool = True

    def as_dict(self) -> dict:
        return {
            "action": self.name,
            "risk": self.risk.label,
            "description": self.description,
            "target": self.target,
            "reversible": self.reversible,
        }


# Every action the assistant can take, and its risk. This table is the single
# answer to "is that dangerous", so it is written out rather than inferred from
# names, which would let a new skill be "low risk" by accident.
POLICY: dict[str, Action] = {}


def _register(action: Action) -> Action:
    POLICY[action.name] = action
    return action


# --------------------------------------------------------------- low risk
# These do what they say and nothing else. They read, or they open something the
# user can see and close again.
for _name, _description in {
    "tell_time": "tell the time",
    "tell_date": "tell the date",
    "greet": "greet the user",
    "take_screenshot": "take a screenshot",
    "open_application": "open an installed application",
    "open_website": "open a website in the browser",
    "search_web": "search the web",
    "lookup_wikipedia": "read an article",
    "search_files": "search for files",
    "read_document": "read a document aloud",
    "list_folder": "show what is in a folder",
    "open_folder": "open a folder",
    "tell_joke": "tell a joke",
    "set_input_mode": "switch between voice and keyboard",
    "set_volume": "change the volume",
    "set_muted": "stop or resume speaking",
    "answer_question": "answer a question",
    "recall_memory": "say what is remembered",
    "list_skills": "describe what the assistant can do",
    "set_assistant_name": "rename the assistant",
}.items():
    _register(Action(_name, Risk.LOW, _description))

# ------------------------------------------------------------- medium risk
# Changes something, but the change is obvious and small.
for _name, _description in {
    "move_file": "move a file",
    "copy_file": "copy a file",
    "rename_file": "rename a file",
    "create_file": "create a file",
    "write_note": "write a note",
    "change_setting": "change a setting",
    "close_application": "close an application",
    "play_media": "play a song or a video",
}.items():
    _register(Action(_name, Risk.MEDIUM, _description, reversible=True))

# --------------------------------------------------------------- high risk
# Data is lost or the machine stops. None of these ever happen without an
# answer, whatever the configuration says.
for _name, _description in {
    "delete_file": "delete a file",
    "delete_folder": "delete a folder",
    "empty_recycle_bin": "empty the Recycle Bin",
    "shutdown": "shut Windows down",
    "restart": "restart Windows",
    "log_off": "log off of Windows",
    "format_drive": "erase a drive",
    "execute_command": "run a system command",
    "change_security_setting": "change a security setting",
    "edit_registry": "edit the Windows registry",
}.items():
    _register(Action(
        _name, Risk.HIGH, _description,
        # Anything that destroys data rather than putting it in the Recycle Bin
        # cannot be undone, and the prompt says so rather than promising a way
        # back.
        reversible=_name not in {
            "format_drive", "empty_recycle_bin", "shutdown", "restart",
            "log_off", "execute_command", "delete_file", "delete_folder",
            "change_security_setting", "edit_registry",
        },
    ))

# Actions that cannot be undone, which is what the prompt wording depends on.
IRREVERSIBLE = frozenset(
    name for name, action in POLICY.items() if not action.reversible
)

# Actions that are high risk however they are reached. Automation cannot offer a
# way round the table.
NEVER_UNCONFIRMED = frozenset(
    name for name, action in POLICY.items() if action.risk is Risk.HIGH
)

# Anything reaching a shell at all. Kept as a named set so the intent is obvious
# at every place that would otherwise be tempted to add one.
COMMAND_ACTIONS = frozenset({"execute_command"})


@dataclass(frozen=True)
class Decision:
    """What the policy decided about one action."""

    action: Action
    allowed: bool
    needs_confirmation: bool
    reason: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            **self.action.as_dict(),
            "allowed": self.allowed,
            "needs_confirmation": self.needs_confirmation,
            "reason": self.reason,
        }


def describe(name: str, target: str = "") -> Action:
    """The policy entry for an action.

    An action nobody declared is treated as high risk rather than low. Guessing
    low would mean a new skill was trusted by default, which is exactly the
    mistake worth refusing to make.
    """
    action = POLICY.get(name)
    if action is not None:
        return action if not target else Action(
            action.name, action.risk, action.description, target,
            action.reversible,
        )
    return Action(name, Risk.HIGH, f"unrecognised action: {name}", target)


def classify(name: str, target: str = "") -> Risk:
    """How risky an action is."""
    return describe(name, target).risk


def needs_confirmation(
    name: str,
    target: str = "",
    confirm_dangerous: bool = True,
    confirm_medium: bool = False,
) -> bool:
    """Whether the user has to be asked first.

    High risk always asks. That is not configurable, because a setting that
    turned it off would be a setting that let a mistaken answer shut down a
    computer.
    """
    risk = classify(name, target)

    if risk is Risk.HIGH:
        return True
    if risk is Risk.MEDIUM:
        return confirm_medium
    return confirm_dangerous and False


def evaluate(
    name: str,
    target: str = "",
    confirm_dangerous: bool = True,
    confirm_medium: bool = False,
    permitted: frozenset | None = None,
) -> Decision:
    """The full decision about one action, ready to be logged or shown."""
    if name not in POLICY:
        # Nobody declared this action, so it is refused rather than treated as
        # harmless. A name that turns up in a skill but not in the table is a
        # mistake, and a mistake should stop rather than be guessed at.
        return Decision(
            Action(name, Risk.HIGH, f"unrecognised action: {name}", target),
            allowed=False, needs_confirmation=True,
            reason="this action is not in the safety policy",
        )

    action = describe(name, target)

    if permitted is not None and name not in permitted:
        return Decision(
            action, allowed=False, needs_confirmation=False,
            reason="this action is not permitted",
        )

    if name in COMMAND_ACTIONS:
        return Decision(
            action, allowed=False, needs_confirmation=True,
            reason="running an arbitrary command is not supported",
        )

    ask = needs_confirmation(
        name, target, confirm_dangerous, confirm_medium
    )
    reason = ""
    if ask:
        reason = (
            f"{action.description or name} cannot be undone"
            if not action.reversible
            else f"{action.description or name} changes something"
        )
    return Decision(action, allowed=True, needs_confirmation=ask, reason=reason)


def prompt_for(action: Action) -> str:
    """The question to put to the user, naming what will happen."""
    if action.name in {"delete_file", "delete_folder"}:
        return (
            f"Permanently delete {action.target or 'this'}? "
            "It will not go to the Recycle Bin."
        )
    if action.name == "format_drive":
        target = action.target or "this drive"
        return f"Erase everything on {target}? This cannot be undone."
    if action.name == "shutdown":
        return "Shut down Windows now? Anything you have not saved will be lost."
    if action.name == "restart":
        return "Restart Windows now? Anything you have not saved will be lost."
    if action.name == "execute_command":
        return (f"Run {action.target or 'this command'}? Jarvis does not run "
                "arbitrary commands.")
    if not action.reversible:
        what = action.description or action.name
        return f"{what} {action.target}? This cannot be undone."

    return f"{action.description or action.name} {action.target}?"


def risk_counts() -> dict:
    """How many actions sit at each level, for the dashboard."""
    counts = {level.label: 0 for level in Risk}
    for action in POLICY.values():
        counts[action.risk.label] += 1
    return counts
