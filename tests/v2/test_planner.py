"""Multi-step tasks: splitting a request, checking the plan, running it."""

import pytest

from jarvis2.ai.planner import Plan, Planner, PlanStep, split_clauses
from jarvis2.ai.provider import ToolCall
from jarvis2.ai.providers.mock import MockAIProvider
from jarvis2.core.conversation import Conversation
from jarvis2.core.models import Request, Response, Source, Status
from jarvis2.skills import build_default_registry


def request_for(text: str) -> Request:
    return Request(text=text, source=Source.TERMINAL)


class TestSplitClauses:
    @pytest.mark.parametrize("text,expected", [
        ("open my cv and open my downloads", 2),
        ("play gospel and open youtube", 2),
        ("open downloads and then open documents", 2),
    ])
    def test_two_instructions_are_split(self, text, expected):
        assert len(split_clauses(text)) == expected

    @pytest.mark.parametrize("text", [
        "rock and roll",
        "salt and pepper",
        "black and white",
        "guns and roses",
    ])
    def test_a_phrase_is_not_two_instructions(self, text):
        # Splitting on "and" alone would turn one request into two, and the
        # second would have nothing to do.
        assert len(split_clauses(text)) == 1

    def test_a_single_command_is_not_split(self):
        assert split_clauses("open my cv") == ["open my cv"]

    def test_a_trailing_connector_is_ignored(self):
        assert len(split_clauses("open my cv and")) == 1


class TestPlanFromRequest:
    @pytest.fixture
    def planner(self):
        registry = build_default_registry()
        return Planner(registry, Conversation(), runner=self._runner)

    def _runner(self, step, request):
        return Response(text=f"did {step.tool}", source=Source.TERMINAL)

    async def test_two_actions_make_a_plan(self, planner):
        plan = await planner.from_request(request_for("open downloads and open music"))
        assert len(plan) == 2
        assert [step.tool for step in plan.steps] == ["files", "files"]

    async def test_one_action_makes_no_plan(self, planner):
        # Otherwise every ordinary request would go through the planner.
        plan = await planner.from_request(request_for("open downloads"))
        assert len(plan) == 0

    async def test_a_coherent_half_and_a_nonsense_half_is_one_request(
    self, planner
):
        # "flibbertigibbet the widgets" is not an instruction, so the sentence
        # is not split in two and nothing is run. Running the real half and
        # ignoring the other would be a guess.
        plan = await planner.from_request(
            request_for("open downloads and flibbertigibbet the widgets")
        )
        assert all(not step.runnable for step in plan.steps)


class TestPlanFromModel:
    @pytest.fixture
    def planner(self):
        registry = build_default_registry()
        return Planner(registry, Conversation(), runner=self._runner)

    def _runner(self, step, request):
        return Response(text=f"did {step.tool}", source=Source.TERMINAL)

    async def test_a_model_plan_is_built(self, planner):
        provider = MockAIProvider(
            tool_calls=[ToolCall("run_task", {"steps": [
                {"tool": "documents", "arguments": {"query": "cv"}},
                {"tool": "files", "arguments": {"query": "downloads"}},
            ]})]
        )
        plan = await planner.from_model(request_for("open my cv and my downloads"),
                                        provider)
        assert len(plan) == 2
        assert plan.steps[0].tool == "documents"

    async def test_a_tool_the_model_invents_is_not_runnable(self, planner):
        provider = MockAIProvider(
            tool_calls=[ToolCall("run_task", {"steps": [
                {"tool": "documents", "arguments": {"query": "cv"}},
                {"tool": "rm_rf_slash", "arguments": {}},
            ]})]
        )
        plan = await planner.from_model(request_for("do something"), provider)

        assert plan.steps[1].runnable is False
        # Not mapped to the nearest thing: a model's mistake stops here.
        assert "unknown tool" in plan.steps[1].text

    async def test_a_plan_stops_at_a_step_that_cannot_run(self, planner):
        provider = MockAIProvider(
            tool_calls=[ToolCall("run_task", {"steps": [
                {"tool": "nonsense", "arguments": {}},
                {"tool": "files", "arguments": {"query": "downloads"}},
            ]})]
        )
        plan = await planner.from_model(request_for("do something"), provider)

        # Everything after a step that cannot run is cancelled too, because a
        # plan that started differently does not mean the same thing half way
        # through.
        assert plan.steps[1].runnable is False
        assert plan.stopped_because

    async def test_with_no_model_the_split_is_used(self, planner):
        plan = await planner.from_model(
            request_for("open downloads and open music"), None
        )
        assert len(plan) == 2

    async def test_a_model_that_says_nothing_falls_back(self, planner):
        plan = await planner.from_model(
            request_for("open downloads and open music"),
            MockAIProvider(responses="I am not sure."))
        assert len(plan) == 2


class TestRunningAPlan:
    def _planner(self, outcomes):
        registry = build_default_registry()
        results = list(outcomes)

        async def runner(step, request):
            return results.pop(0) if results else Response(
                text="nothing left", status=Status.FAILED
            )

        return Planner(registry, Conversation(), runner=runner)

    async def test_every_step_runs(self):
        planner = self._planner([
            Response(text="opened cv"),
            Response(text="opened downloads"),
        ])
        plan = Plan(goal="x", steps=[
            PlanStep(tool="documents", text="open my cv"),
            PlanStep(tool="files", text="open downloads"),
        ])
        results = await planner.run(plan, request_for("x"))
        assert len(results) == 2
        assert all(step.result is not None for step in plan.steps)

    async def test_a_step_that_needs_the_user_stops_the_rest(self):
        planner = self._planner([
            Response(text="which one?", status=Status.NEEDS_CLARIFICATION,
                     question="Which one?"),
            Response(text="should not run"),
        ])
        plan = Plan(goal="x", steps=[
            PlanStep(tool="documents", text="open my cv"),
            PlanStep(tool="files", text="open downloads"),
        ])
        results = await planner.run(plan, request_for("x"))

        # Continuing would mean doing the rest out of order.
        assert len(results) == 1
        assert plan.stopped_because == "which one?"
        assert plan.steps[1].runnable is False

    async def test_a_failed_step_stops_the_rest(self):
        planner = self._planner([
            Response(text="no matches", status=Status.FAILED),
            Response(text="should not run"),
        ])
        plan = Plan(goal="x", steps=[
            PlanStep(tool="documents", text="open my cv"),
            PlanStep(tool="files", text="open downloads"),
        ])
        results = await planner.run(plan, request_for("x"))
        assert len(results) == 1

    async def test_a_confirmation_stops_the_rest(self):
        planner = self._planner([
            Response(text="Shut down Windows?", status=Status.NEEDS_CONFIRMATION),
            Response(text="should not run"),
        ])
        plan = Plan(goal="x", steps=[
            PlanStep(tool="power", text="shutdown"),
            PlanStep(tool="files", text="open downloads"),
        ])
        results = await planner.run(plan, request_for("x"))
        assert len(results) == 1

    async def test_an_empty_plan_does_nothing(self):
        planner = self._planner([])
        assert await planner.run(Plan(goal="x"), request_for("x")) == []

    async def test_a_plan_is_described_in_words(self):
        planner = self._planner([])
        plan = Plan(goal="x", steps=[
            PlanStep(tool="documents", text="open my cv"),
            PlanStep(tool="files", text="open downloads"),
        ])
        assert planner.describe(plan) == "open my cv, then open downloads"
