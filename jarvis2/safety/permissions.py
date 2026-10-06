"""What this installation of Jarvis is allowed to do.

A skill declares the actions it performs. The registry checks that declaration
against this set before anything runs, so a skill cannot reach an action it did
not ask for, and turning an action off here stops every route to it.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis2.safety import policy


@dataclass
class PermissionSet:
    """Which actions are on, and how risky each one is allowed to be."""

    allowed: frozenset = frozenset()
    # Where the set came from, for the dashboard: "defaults", "session", "config".
    source: str = "defaults"

    def permits(self, action: str) -> bool:
        return action in self.allowed

    def with_actions(self, *actions: str, source: str = "") -> PermissionSet:
        return PermissionSet(
            allowed=frozenset(self.allowed) | frozenset(actions),
            source=source or self.source,
        )

    def without(self, *actions: str) -> PermissionSet:
        return PermissionSet(
            allowed=frozenset(self.allowed) - frozenset(actions),
            source=self.source,
        )

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "allowed": sorted(self.allowed),
            "denied": sorted(
                name for name in policy.POLICY if name not in self.allowed
            ),
        }


# Two separate questions, kept separate on purpose:
#
#   permitted    may this installation do this at all?
#   confirmed    does the user have to be asked first?
#
# Everything in the policy table is permitted, because a high risk action that
# is permitted and always confirmed is the whole design. What is not permitted is
# anything the policy refuses outright: running an arbitrary command has no
# route in, so declaring a skill for it is an error at registration rather than
# something discovered when somebody asks for it.
#
# Confirming a high risk action is not a setting. See policy.needs_confirmation.
DEFAULT_ALLOWED = frozenset(
    name for name, action in policy.POLICY.items()
    if name not in policy.COMMAND_ACTIONS
)

# Medium risk actions a user can opt into, with confirmation still on for
# anything high risk.
DEFAULT_MEDIUM = frozenset({
    "play_media", "close_application", "set_volume", "set_muted",
})


def default_permissions() -> PermissionSet:
    return PermissionSet(
        allowed=frozenset(DEFAULT_ALLOWED | DEFAULT_MEDIUM),
        source="defaults",
    )


class PermissionError_(PermissionError):
    """Raised when a skill asks for something this installation may not do."""


def require(permissions: PermissionSet, actions) -> None:
    """Checks a skill's declared actions against what is allowed.

    An unknown action counts as denied. A typo in a name should stop the skill
    rather than quietly let an undeclared action through.
    """
    if isinstance(actions, str):
        actions = [actions]

    unknown = [
        name for name in actions
        if name not in policy.POLICY
    ]
    if unknown:
        raise PermissionError_(
            f"unknown action(s) declared: {', '.join(sorted(unknown))}"
        )

    denied = [name for name in actions if not permissions.permits(name)]
    if denied:
        raise PermissionError_(
            f"this Jarvis is not allowed to: {', '.join(sorted(denied))}"
        )


def highest_risk(actions) -> policy.Risk:
    """The risk of the worst thing in a set of actions."""
    if isinstance(actions, str):
        actions = [actions]
    risks = [policy.classify(name) for name in actions]
    return max(risks, default=policy.Risk.LOW)
