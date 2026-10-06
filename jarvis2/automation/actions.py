"""Automation.

A short list of steps that can be run, each one allowlisted and validated. The
allowlist is the point: a model may ask for a step by name, and only a name on
this list can be run, with its arguments checked before it happens.

There is deliberately no way to run a shell command. Not disabled, not gated
behind a setting, absent. A command runner reached by a language model is the
hole everything else is built to keep closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis2.core.models import Response, Status
from jarvis2.logging_utils import get_logger
from jarvis2.safety import paths as path_safety
from jarvis2.safety.policy import Risk, evaluate

_log = get_logger("automation")


@dataclass
class Step:
    """One allowlisted action."""

    name: str
    action: str
    description: str
    #: What the step needs, and how it must look.
    argument: str = "path"
    risk: Risk = Risk.LOW
    validate: str = "path"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "action": self.action,
            "description": self.description,
            "argument": self.argument,
            "risk": self.risk.label,
        }


# The complete list. Anything not named here cannot be run.
STEPS: dict[str, Step] = {}


def _step(name: str, action: str, description: str, **kwargs) -> Step:
    entry = Step(name=name, action=action, description=description, **kwargs)
    STEPS[name] = entry
    return entry


_step("open_file", "open_application", "Open a file in its usual program",
      validate="document")
_step("open_folder", "open_folder", "Open a folder")
_step("create_folder", "create_file", "Create a folder",
      validate="new_folder", risk=Risk.MEDIUM)
_step("move_file", "move_file", "Move a file somewhere else",
      validate="two_paths", risk=Risk.MEDIUM)
_step("copy_file", "copy_file", "Copy a file", validate="two_paths",
      risk=Risk.MEDIUM)
_step("write_note", "write_note", "Write a text note", validate="new_file",
      risk=Risk.MEDIUM)
_step("delete_file", "delete_file", "Delete a file", validate="path",
      risk=Risk.HIGH)
_step("take_screenshot", "take_screenshot", "Take a screenshot")


def describe() -> list:
    return [step.as_dict() for step in STEPS.values()]


class AutomationRefused(Exception):
    """Raised when a step is not one this installation will run."""


class Automation:
    """Runs allowlisted steps, checking each one before it happens."""

    def __init__(self, settings, confirmations, runner, enabled: bool = False):
        self.settings = settings
        self.confirmations = confirmations
        #: Called as runner(function, *args) for each step.
        self.runner = runner
        self.enabled = enabled

    # ------------------------------------------------------------------
    def knows(self, name: str) -> bool:
        return name in STEPS

    def describe(self) -> dict:
        return {
            "enabled": self.enabled,
            "steps": describe(),
        }

    async def run(self, name: str, argument: str = "",
                  second: str = "") -> Response:
        """Runs one step, or returns why it will not."""
        step = STEPS.get(name)
        if step is None:
            raise AutomationRefused(
                f"there is no automated step called {name!r}"
            )

        if not self.enabled:
            raise AutomationRefused(
                "automation is switched off. Turn it on in settings if you "
                "want Jarvis to act on its own."
            )

        # The action is checked before the step is even looked at, so a step
        # cannot declare something the policy refuses.
        decision = evaluate(
            step.action,
            confirm_dangerous=self.settings.confirm_dangerous_actions,
        )
        if not decision.allowed:
            raise AutomationRefused(decision.reason)

        verdict = self._validate(step, argument, second)
        if verdict is not None:
            raise AutomationRefused(verdict)

        async def carry_out():
            return await self._perform(step, argument, second)

        if decision.needs_confirmation:
            confirmation = self.confirmations.ask(
                decision.action, carry_out,
                details={"step": step.name, "target": argument},
            )
            return Response(
                text=confirmation.prompt,
                status=Status.NEEDS_CONFIRMATION,
                confirmation=confirmation,
                actions=[{"action": "automation_requested", "target": step.name}],
            )

        return await carry_out()

    # ------------------------------------------------------------------
    def _validate(self, step: Step, argument: str,
                  second: str) -> str | None:
        """Why this step's arguments are not acceptable, or None."""
        if not argument:
            return f"{step.description} needs a path."

        if step.validate == "two_paths":
            if not second:
                return f"{step.description} needs two paths."
            for path in (argument, second):
                checked = path_safety.validate(path)
                if not checked.allowed:
                    return checked.reason
                if not path_safety.is_safe_to_delete(checked.path) \
                        and step.action in {"delete_file"}:
                    return "that is not somewhere I should be deleting things."
            return None

        if step.validate in {"path", "document"}:
            checked = path_safety.validate(
                argument, expect="document" if step.validate == "document" else "any"
            )
            if not checked.allowed:
                return checked.reason
            return None

        if step.validate in {"new_file", "new_folder"}:
            folder = path_safety.resolve(argument).parent
            if not folder.is_dir():
                return f"There is no {folder.name} folder to put it in."
            if path_safety.is_protected(folder):
                return "that is a system folder, so Jarvis will not write there."
            return None

        if step.validate == "new_folder":
            return None

        return None

    async def _perform(self, step: Step, argument: str,
                       second: str) -> Response:
        """Carries the step out. Only reached once every check has passed."""
        import os
        import shutil

        name = step.name

        if name == "take_screenshot":
            return await self._screenshot()

        if name == "write_note":
            target = path_safety.resolve(argument)

            def write():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(second, encoding="utf-8")
                return str(target)

            written = await self.runner(write)
            return Response(
                text=f"Written to {path_safety.display(written)}.",
                status=Status.OK,
                opened=[written],
                actions=[{"action": "write_note", "target": written}],
            )

        if name == "create_folder":
            target = path_safety.resolve(argument)

            def make():
                os.makedirs(target, exist_ok=True)
                return str(target)

            made = await self.runner(make)
            return Response(
                text=f"Created {path_safety.display(made)}.",
                status=Status.OK,
                opened=[made],
                actions=[{"action": "create_folder", "target": made}],
            )

        if name in {"move_file", "copy_file"}:
            source = path_safety.resolve(argument)
            destination = path_safety.resolve(second)

            def move():
                shutil.move(str(source), str(destination))
                return str(destination)

            moved = await self.runner(move)
            verb = "Moved to" if name == "move_file" else "Copied to"
            return Response(
                text=f"{verb} {path_safety.display(moved)}.",
                status=Status.OK,
                opened=[moved],
                actions=[{"action": name, "target": moved}],
            )

        if name == "delete_file":
            target = path_safety.resolve(argument)

            def remove():
                os.remove(target)
                return str(target)

            removed = await self.runner(remove)
            return Response(
                text=f"Deleted {path_safety.display(removed)}.",
                status=Status.OK,
                actions=[{"action": "delete_file", "target": removed}],
            )

        target = path_safety.resolve(argument)

        def open_it():
            os.startfile(target)
            return str(target)

        opened = await self.runner(open_it)
        return Response(
            text=f"Opening {path_safety.display(opened)}.",
            status=Status.OK,
            opened=[opened],
            actions=[{"action": step.action, "target": opened}],
        )

    async def _screenshot(self) -> Response:
        import os

        def take():
            import pyautogui

            home = os.path.expanduser("~")
            image = pyautogui.screenshot()
            for name in ("Pictures", "Desktop", "Downloads"):
                folder = os.path.join(home, name)
                try:
                    os.makedirs(folder, exist_ok=True)
                    target = os.path.join(folder, "screenshot.png")
                    image.save(target)
                    return target
                except OSError:
                    continue
            return ""

        saved = await self.runner(take)
        if not saved:
            return Response(
                text="I took the screenshot but could not save it anywhere.",
                status=Status.FAILED,
            )
        return Response(
            text=f"Screenshot saved as {path_safety.display(saved)}.",
            status=Status.OK,
            opened=[saved],
            actions=[{"action": "take_screenshot", "target": saved}],
        )
