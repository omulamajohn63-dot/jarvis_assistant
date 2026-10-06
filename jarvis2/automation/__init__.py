"""Automation, with a short list of allowlisted steps.

There is no shell here, and none is planned. A command runner a language model
can reach is the thing the whole safety layer exists to prevent.
"""

from jarvis2.automation.actions import (
    STEPS,
    Automation,
    AutomationRefused,
    Step,
    describe,
)
from jarvis2.automation.executor import Executor, Task, TaskStep, describe_tasks

__all__ = [
    "STEPS",
    "Automation",
    "AutomationRefused",
    "Executor",
    "Step",
    "Task",
    "TaskStep",
    "describe",
    "describe_tasks",
]
