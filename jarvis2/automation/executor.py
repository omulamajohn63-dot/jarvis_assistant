"""Running one step, and a few steps together."""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis2.automation.actions import Automation, AutomationRefused
from jarvis2.core.models import Response, Status
from jarvis2.logging_utils import get_logger

_log = get_logger("executor")


@dataclass
class TaskStep:
    """One step of a task, with the arguments it needs."""

    step: str
    argument: str = ""
    second: str = ""

    def as_dict(self) -> dict:
        return {"step": self.step, "argument": self.argument,
                "second": self.second}


@dataclass
class Task:
    """A named sequence of steps."""

    name: str
    description: str = ""
    steps: list = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.steps)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [step.as_dict() for step in self.steps],
        }


# Tasks a person would ask for more than once. Kept small and boring on purpose:
# anything clever here would be a thing that runs by itself.
TASKS: dict[str, Task] = {}


def _task(name: str, description: str, *steps: tuple) -> Task:
    entry = Task(
        name=name, description=description,
        steps=[TaskStep(*step) for step in steps],
    )
    TASKS[name] = entry
    return entry


_task("screenshot", "Take a screenshot and save it to your Pictures folder",
      ("take_screenshot",))
_task("open_downloads", "Open your Downloads folder",
      ("open_folder", "~/Downloads"))


def describe_tasks() -> list:
    return [task.as_dict() for task in TASKS.values()]


class Executor:
    """Runs a task, one step at a time, stopping where it must.

    A step that fails or needs the user stops the rest. Continuing would mean
    doing later steps out of order, and a task is only correct in order.
    """

    def __init__(self, automation: Automation):
        self.automation = automation

    async def run_step(self, step: TaskStep) -> Response:
        return await self.automation.run(step.step, step.argument, step.second)

    async def run_task(self, task: Task) -> list:
        results = []
        for index, step in enumerate(task.steps):
            try:
                response = await self.run_step(step)
            except AutomationRefused as refused:
                results.append(Response(
                    text=str(refused), status=Status.FAILED,
                ))
                break
            except Exception as error:
                _log.exception("step %s failed", step.step)
                results.append(Response(
                    text=f"I could not do that: {type(error).__name__}.",
                    status=Status.FAILED, error=str(error),
                ))
                break

            results.append(response)

            if response.needs_input or response.status in {
                Status.FAILED, Status.STOP,
            }:
                # The rest is not attempted. A task that stopped part way
                # through has not done the rest, and saying otherwise would be
                # the worst possible answer.
                for _later in task.steps[index + 1:]:
                    results.append(Response(
                        text="Not done, because the step before it did not "
                             "work out.",
                        status=Status.CANCELLED,
                    ))
                break

        return results

    async def run_named(self, name: str) -> list:
        task = TASKS.get(name)
        if task is None:
            return [Response(
                text=f"There is no task called {name!r}.",
                status=Status.FAILED,
            )]
        return await self.run_task(task)

    def summary(self, results: list) -> Response:
        """One reply describing what a whole task did."""
        if not results:
            return Response(text="There was nothing to do.",
                            status=Status.FAILED)

        done = [entry for entry in results if entry.ok]
        asked = [entry for entry in results if entry.needs_input]
        failed = [entry for entry in results if entry.status is Status.FAILED]

        if asked:
            return asked[0]
        if failed:
            return failed[0]

        opened = [path for entry in done for path in entry.opened]
        text = (
            f"Done. {len(done)} step"
            f"{'' if len(done) == 1 else 's'} done."
        )
        return Response(
            text=text, status=Status.OK, opened=opened,
            actions=[action for entry in done for action in entry.actions],
        )
