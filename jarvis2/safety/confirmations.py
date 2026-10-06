"""Holding an action until the user has answered.

The confirmation is stored rather than asked on stdin, for two reasons. A
browser has to be able to put the question in the page and post the answer back,
and nothing should block on an answer that may never arrive.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any

from jarvis2.core.models import Confirmation
from jarvis2.safety import policy


@dataclass
class HeldAction:
    """An action waiting for an answer, and the callable that would carry it out."""

    confirmation: Confirmation
    # What to do once approved. Stored as a callable so the arguments cannot be
    # changed between asking and answering.
    run: Any
    created_at: float = field(default_factory=time.time)
    # True once answered, so a second click cannot run it again.
    answered: bool = False


class ConfirmationManager:
    """Keeps the held actions and decides whether an answer is the right one.

    One id is only ever good once. That is the whole point: a dialog left open in
    a browser, a retried request, or a double click must not be able to run an
    action that has already been answered or to approve a different one.
    """

    def __init__(self, confirm_dangerous: bool = True,
                 confirm_medium: bool = False):
        self.confirm_dangerous = confirm_dangerous
        self.confirm_medium = confirm_medium
        self._held: dict[str, HeldAction] = {}
        self._counter = itertools.count(1)
        self._history: list = []

    # ------------------------------------------------------------------
    def ask(self, action: policy.Action, run, details: dict | None = None,
            ) -> Confirmation:
        """Holds an action and returns the question to put to the user."""
        confirmation = Confirmation(
            id=str(next(self._counter)),
            action=action.name,
            risk=action.risk.label,
            prompt=policy.prompt_for(action),
            # Copied, so a caller editing its own dict afterwards cannot change
            # what the question says or what the action will act on.
            details=dict(details or {}),
        )
        self._held[confirmation.id] = HeldAction(
            confirmation=confirmation, run=run,
        )
        return confirmation

    def evaluate_and_ask(self, name: str, target: str, run,
                         details: dict | None = None) -> Confirmation | None:
        """Checks an action and, if it needs an answer, holds it.

        Returns None when the action may run without asking. ``run`` is not
        called here: the caller decides, so that a confirmed action goes through
        exactly the same execution path as an unconfirmed one.
        """
        decision = policy.evaluate(
            name, target,
            confirm_dangerous=self.confirm_dangerous,
            confirm_medium=self.confirm_medium,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason or "not allowed")

        if not decision.needs_confirmation:
            return None
        return self.ask(decision.action, run, details)

    # ------------------------------------------------------------------
    @property
    def pending(self) -> Confirmation | None:
        if not self._held:
            return None
        return next(iter(self._held.values())).confirmation

    def is_pending(self, confirmation_id: str | None) -> bool:
        return str(confirmation_id) in self._held

    async def resolve(self, confirmation_id: str, approved: bool,
                      reject=None) -> tuple:
        """Answers a held action and runs it if it was approved.

        Returns (ran, message). ``reject`` is called instead of the action when
        the answer is "no", so a refusal can be reported plainly.
        """
        key = str(confirmation_id)
        held = self._held.get(key)
        if held is None:
            return False, "There is nothing waiting for your answer."
        if held.answered:
            return False, "That has already been answered."

        held.answered = True
        self._held.pop(key, None)
        self._history.append({
            "id": key,
            "action": held.confirmation.action,
            "approved": approved,
            "at": time.time(),
        })

        if not approved:
            if reject is not None:
                reject()
            return False, "Okay, I will not do that."

        result = held.run()
        if hasattr(result, "__await__"):
            result = await result
        return True, result

    def cancel(self, confirmation_id: str) -> bool:
        """Drops a held action without running it."""
        return self._held.pop(str(confirmation_id), None) is not None

    def cancel_all(self) -> int:
        count = len(self._held)
        self._held.clear()
        return count

    def clear_history(self) -> None:
        self._history.clear()

    @property
    def history(self) -> list:
        return list(self._history)

    def history_for(self, confirmation_id: str) -> dict | None:
        for entry in self._history:
            if entry["id"] == str(confirmation_id):
                return entry
        return None
