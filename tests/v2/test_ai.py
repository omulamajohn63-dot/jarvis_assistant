"""The AI layer: the provider seam, what the model is told, and what it may do.

Nothing here reaches a real model. The point of this module is that a test can
say exactly what the model was asked and exactly what it was allowed to answer.
"""


import pytest

from jarvis2.ai.prompts import bound_messages, build_system_prompt
from jarvis2.ai.provider import (
    ProviderError,
    ProviderUnavailable,
    ToolCall,
    coerce_arguments,
    parse_json,
)
from jarvis2.ai.providers import build_provider
from jarvis2.ai.providers.gemini import GeminiProvider
from jarvis2.ai.providers.mock import MockAIProvider, failing, scripted
from jarvis2.ai.providers.openai_compatible import OpenAICompatibleProvider
from jarvis2.ai.response import ResponseBuilder, ToolValidator
from jarvis2.config.settings import Settings
from jarvis2.core.conversation import Conversation
from jarvis2.core.models import Request, Source
from jarvis2.skills import build_default_registry


def request_for(text: str) -> Request:
    return Request(text=text, source=Source.TERMINAL)


class FakeResponse:
    """A stand-in for a requests response, so no socket is opened."""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers,
                           "timeout": timeout})
        return self.response


class TestParseJson:
    def test_plain_json(self):
        assert parse_json('{"a": 1}') == {"a": 1}

    def test_wrapped_in_prose(self):
        # Models wrap JSON in words even when told not to.
        assert parse_json('Sure! Here you go: {"a": 1} Hope that helps.') == {"a": 1}

    def test_in_a_code_fence(self):
        assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_nothing_to_parse(self):
        assert parse_json("just words") is None

    def test_empty(self):
        assert parse_json("") is None

    def test_not_an_object(self):
        assert parse_json("[1, 2, 3]") is None

    def test_arguments_from_a_string(self):
        assert coerce_arguments('{"name": "chrome"}') == {"name": "chrome"}
        assert coerce_arguments("") == {}
        assert coerce_arguments(None) == {}


class TestOpenAICompatible:
    def provider(self, response=None, **kwargs):
        settings = {"api_key": "sk-test", "model": "gpt-test"}
        settings.update(kwargs)
        return OpenAICompatibleProvider(session=FakeSession(response or {}),
                                        **settings)

    async def test_it_needs_a_key_and_a_model(self):
        assert await OpenAICompatibleProvider("", "").available() is False
        assert await OpenAICompatibleProvider("k", "m").available() is True

    async def test_it_refuses_without_a_key(self):
        with pytest.raises(ProviderUnavailable):
            await OpenAICompatibleProvider("", "m").generate([])

    async def test_a_text_reply(self):
        provider = self.provider(FakeResponse({
            "model": "gpt-test",
            "choices": [{"message": {"content": "Hello there."},
                         "finish_reason": "stop"}],
        }))
        answer = await provider.generate([{"role": "user", "content": "hi"}])
        assert answer.text == "Hello there."
        assert answer.wants_a_tool is False

    async def test_a_tool_call(self):
        provider = self.provider(FakeResponse({
            "choices": [{"message": {
                "content": "",
                "tool_calls": [{"id": "1", "function": {
                    "name": "documents", "arguments": '{"query": "cv"}'}}],
            }}],
        }))
        answer = await provider.generate([{"role": "user", "content": "open cv"}])

        assert answer.wants_a_tool is True
        call = answer.tool_calls[0]
        assert call.name == "documents"
        assert call.arguments == {"query": "cv"}

    async def test_the_key_goes_in_a_header(self):
        session = FakeSession(FakeResponse({"choices": [
            {"message": {"content": "hi"}}]}))
        provider = OpenAICompatibleProvider("sk-secret", "m", session=session)
        await provider.generate([{"role": "user", "content": "hi"}])
        # Not in the URL, which is far more likely to end up in a log.
        assert session.calls[0]["headers"]["Authorization"] == "Bearer sk-secret"
        assert "sk-secret" not in session.calls[0]["url"]

    async def test_a_local_server_is_not_given_a_key_it_will_reject(self):
        settings = Settings(ai_provider="openai", ai_model="llama",
                            ai_api_key="sk-ignored",
                            ai_base_url="http://localhost:11434/v1")
        provider = build_provider(settings)
        assert provider is not None
        assert provider.send_auth_header is False

    async def test_a_local_server_needs_no_key(self):
        settings = Settings(ai_provider="openai", ai_model="llama",
                            ai_api_key="",
                            ai_base_url="http://localhost:11434/v1")
        assert build_provider(settings) is not None

    async def test_a_refused_key_is_an_error(self):
        with pytest.raises(ProviderError, match="rejected"):
            await self.provider(FakeResponse({}, 401)).generate([])

    async def test_rate_limiting_is_unavailable_not_an_error(self):
        # Worth retrying later, so it is reported as "cannot reach" rather than
        # as a broken reply.
        with pytest.raises(ProviderUnavailable):
            await self.provider(FakeResponse({}, 429)).generate([])

    async def test_a_reply_that_is_not_json_is_an_error(self):
        with pytest.raises(ProviderError, match="not JSON"):
            await self.provider(FakeResponse(ValueError("nope"))).generate([])

    async def test_no_choices_is_an_error(self):
        with pytest.raises(ProviderError, match="no choices"):
            await self.provider(FakeResponse({"choices": []})).generate([])

    async def test_the_tools_are_sent(self):
        session = FakeSession(FakeResponse({"choices": [
            {"message": {"content": "hi"}}]}))
        provider = OpenAICompatibleProvider("k", "m", session=session)
        tools = [{"type": "function", "function": {"name": "clock"}}]
        await provider.generate([{"role": "user", "content": "hi"}], tools=tools)
        assert session.calls[0]["json"]["tools"] == tools


class TestGemini:
    def provider(self, payload, status_code=200, **kwargs):
        session = FakeSession(FakeResponse(payload, status_code))
        return GeminiProvider("AIza-test", "gemini-2.0-flash",
                              session=session, **kwargs)

    async def test_it_needs_a_key(self):
        assert await GeminiProvider("", "gemini-2.0-flash").available() is False

    async def test_a_text_reply(self):
        provider = self.provider({"candidates": [{"content": {"parts": [
            {"text": "Hello there."}]}}]})
        answer = await provider.generate([{"role": "user", "content": "hi"}])
        assert answer.text == "Hello there."

    async def test_the_system_prompt_is_its_own_field(self):
        # Gemini takes the instruction outside the conversation, so it is moved
        # there rather than left as a turn in the wrong place.
        session = FakeSession(FakeResponse({"candidates": [{"content": {
            "parts": [{"text": "ok"}]}}]}))
        provider = GeminiProvider("AIza", "gemini-2.0-flash", session=session)
        await provider.generate([
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "hi"},
        ])
        payload = session.calls[0]["json"]
        assert payload["systemInstruction"]["parts"][0]["text"] == "Be helpful."
        assert len(payload["contents"]) == 1
        assert payload["contents"][0]["role"] == "user"

    async def test_roles_are_translated(self):
        session = FakeSession(FakeResponse({"candidates": [{"content": {
            "parts": [{"text": "ok"}]}}]}))
        provider = GeminiProvider("AIza", "gemini-2.0-flash", session=session)
        await provider.generate([
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ])
        roles = [entry["role"] for entry in session.calls[0]["json"]["contents"]]
        assert roles == ["user", "model"]

    async def test_a_tool_call(self):
        provider = self.provider({"candidates": [{"content": {"parts": [
            {"functionCall": {"name": "documents", "args": {"query": "cv"}}},
        ]}}]})
        answer = await provider.generate([{"role": "user", "content": "open cv"}])
        assert answer.tool_calls[0].name == "documents"
        assert answer.tool_calls[0].arguments == {"query": "cv"}

    async def test_the_key_goes_in_a_header_not_the_url(self):
        session = FakeSession(FakeResponse({"candidates": [{"content": {
            "parts": [{"text": "ok"}]}}]}))
        provider = GeminiProvider("AIza-secret", "gemini-2.0-flash",
                                  session=session)
        await provider.generate([{"role": "user", "content": "hi"}])
        assert session.calls[0]["headers"]["x-goog-api-key"] == "AIza-secret"
        assert "AIza-secret" not in session.calls[0]["url"]

    async def test_tools_become_function_declarations(self):
        session = FakeSession(FakeResponse({"candidates": [{"content": {
            "parts": [{"text": "ok"}]}}]}))
        provider = GeminiProvider("AIza", "gemini-2.0-flash", session=session)
        await provider.generate(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {
                "name": "clock", "description": "Tell the time",
                "parameters": {"type": "object", "additionalProperties": False},
            }}])
        declared = session.calls[0]["json"]["tools"][0]["functionDeclarations"]
        assert declared[0]["name"] == "clock"
        # Gemini rejects a keyword OpenAI accepts, so it is dropped rather than
        # sent on to produce a confusing error.
        assert "additionalProperties" not in declared[0]["parameters"]

    async def test_a_refused_key_is_an_error(self):
        with pytest.raises(ProviderError, match="rejected"):
            await self.provider({}, 403).generate([])

    async def test_a_missing_model_is_named(self):
        with pytest.raises(ProviderError, match="does not exist"):
            await self.provider({}, 404).generate([])

    async def test_a_blocked_request_says_so(self):
        with pytest.raises(ProviderError, match="refused"):
            await self.provider({"promptFeedback": {"blockReason": "SAFETY"}}) \
                .generate([])

    async def test_no_candidates_is_an_error(self):
        with pytest.raises(ProviderError):
            await self.provider({"candidates": []}).generate([])


class TestBuildProvider:
    def test_nothing_configured_gives_nothing(self):
        assert build_provider(Settings()) is None

    def test_disabled_gives_nothing(self):
        settings = Settings(ai_provider="openai", ai_model="m",
                            ai_api_key="k", ai_enabled=False)
        assert build_provider(settings) is None

    def test_openai(self):
        settings = Settings(ai_provider="openai", ai_model="m", ai_api_key="k")
        assert isinstance(build_provider(settings), OpenAICompatibleProvider)

    def test_gemini(self):
        settings = Settings(ai_provider="gemini", ai_model="m",
                            google_api_key="AIzaG")
        assert isinstance(build_provider(settings), GeminiProvider)

    def test_gemini_without_its_key_gives_nothing(self):
        # The two providers use different keys, and a silent swap would be a
        # confusing failure rather than an obvious one.
        settings = Settings(ai_provider="gemini", ai_model="m",
                            ai_api_key="sk-openai")
        assert build_provider(settings) is None

    def test_the_mock(self):
        settings = Settings(ai_provider="mock", ai_model="m")
        assert isinstance(build_provider(settings), MockAIProvider)


class TestMockProvider:
    async def test_a_list_is_used_in_order(self):
        provider = MockAIProvider(responses=["one", "two"])
        assert (await provider.generate([])).text == "one"
        assert (await provider.generate([])).text == "two"
        # The last answer repeats rather than running out.
        assert (await provider.generate([])).text == "two"

    async def test_a_callable_sees_the_messages(self):
        provider = MockAIProvider(
            responses=lambda messages: messages[-1]["content"].upper()
        )
        answer = await provider.generate([{"role": "user", "content": "hi"}])
        assert answer.text == "HI"

    async def test_it_records_what_it_was_asked(self):
        provider = MockAIProvider(responses="ok")
        await provider.generate([{"role": "user", "content": "a question"}])
        assert provider.last_messages[-1]["content"] == "a question"

    async def test_it_can_fail(self):
        from jarvis2.ai.provider import ProviderUnavailable as Unavailable

        provider = MockAIProvider(fail_with=Unavailable("no key"))
        with pytest.raises(Unavailable):
            await provider.generate([])

    def test_scripted(self):
        provider = scripted(("what is python", "A language."))
        assert provider is not None

    async def test_failing(self):
        provider = failing()
        assert await provider.available() is False


class TestPrompts:
    def test_the_tools_come_from_the_registry(self):
        prompt = build_system_prompt(Settings(), build_default_registry())
        # The model is told what the skills are rather than what they contain.
        assert "documents" in prompt
        assert "Find a document by name" in prompt

    def test_the_limits_are_stated(self):
        prompt = build_system_prompt(Settings(), build_default_registry())
        assert "no tool for running shell commands" in prompt
        assert "never write code" in prompt

    def test_the_assistant_name_is_used(self):
        prompt = build_system_prompt(
            Settings(assistant_name="Friday"), build_default_registry()
        )
        assert "You are Friday" in prompt

    def test_memories_are_included(self):
        prompt = build_system_prompt(
            Settings(), build_default_registry(), ["prefers dark mode"]
        )
        assert "prefers dark mode" in prompt

    def test_history_is_bounded(self):
        # An unbounded history is slow, expensive and mostly filler.
        messages = [{"role": "user", "content": f"line {n}"} for n in range(100)]
        bounded = bound_messages(messages, max_turns=5, max_chars=10_000)
        assert len(bounded) <= 11

    def test_characters_are_bounded(self):
        messages = [{"role": "user", "content": "x" * 500} for _ in range(20)]
        bounded = bound_messages(messages, max_turns=50, max_chars=1200)
        total = sum(len(str(entry["content"])) for entry in bounded)
        assert total <= 1200

    def test_the_question_is_never_dropped(self):
        # Cutting it would lose the thing that was actually asked.
        messages = [{"role": "user", "content": "x" * 500} for _ in range(20)]
        messages.append({"role": "user", "content": "the real question"})
        bounded = bound_messages(messages, max_turns=50, max_chars=1200)
        assert bounded[-1]["content"] == "the real question"


class TestToolValidator:
    @pytest.fixture
    def validator(self):
        return ToolValidator(build_default_registry())

    def test_a_real_tool_is_accepted(self, validator):
        skill, error = validator.validate(ToolCall("documents", {"query": "cv"}))
        assert skill is not None
        assert error is None

    def test_an_unknown_tool_is_named_as_such(self, validator):
        # Not mapped to the nearest thing: a model guessing would produce a
        # wrong action under a right name.
        skill, error = validator.validate(ToolCall("delete_everything"))
        assert skill is None
        assert "no tool called" in error

    def test_no_tool_named(self, validator):
        _skill, error = validator.validate(ToolCall(""))
        assert "no tool" in error

    def test_an_unexpected_argument_is_refused(self, validator):
        _skill, error = validator.validate(
            ToolCall("documents", {"query": "cv", "path": "C:/Windows"})
        )
        assert error is not None
        assert "does not take" in error

    def test_arguments_must_be_an_object(self, validator):
        _skill, error = validator.validate(ToolCall("documents", ["cv"]))
        assert "not an object" in error

    def test_a_tool_whose_actions_are_not_permitted(self):
        from jarvis2.safety.permissions import PermissionSet

        validator = ToolValidator(build_default_registry(),
                                  PermissionSet(allowed=frozenset()))
        _skill, error = validator.validate(ToolCall("documents", {"query": "cv"}))
        assert error is not None


class TestResponseBuilder:
    @pytest.fixture
    def builder(self, settings, memory):
        return ResponseBuilder(
            settings, build_default_registry(), Conversation(),
            memory=memory)

    async def test_with_no_provider_the_builder_refuses(self, builder):
        # It refuses rather than reaching for a global one, so a test cannot
        # accidentally call a real model.
        with pytest.raises(ProviderUnavailable):
            await builder.run(request_for("who is einstein"))

    async def test_the_provider_on_the_request_is_used(self, builder):
        provider = MockAIProvider(responses="Python is a language.")
        request = Request(text="what is python", source=Source.TERMINAL,
                          metadata={"provider": provider})
        result = await builder.run(request)
        assert result.succeeded is True
        assert result.text == "Python is a language."

    async def test_the_system_prompt_is_sent(self, builder):
        provider = MockAIProvider(responses="ok")
        request = Request(text="hi", metadata={"provider": provider})
        await builder.run(request)
        assert provider.last_messages[0]["role"] == "system"
        assert "documents" in provider.last_messages[0]["content"]

    async def test_the_tools_are_sent(self, builder):
        provider = MockAIProvider(responses="ok")
        request = Request(text="hi", metadata={"provider": provider})
        await builder.run(request)
        assert provider.last_tools

    async def test_a_failed_tool_is_reported_not_hidden(self, builder):
        provider = MockAIProvider(
            responses=["", "I could not find that."],
            tool_calls=[ToolCall("documents", {"query": "nothing"})],
            tool_rounds=1)

        async def runner(skill, request):
            from jarvis2.core.models import SkillResult
            return SkillResult(succeeded=False, text="No matches.")

        builder.runner = runner
        request = Request(text="open nothing", metadata={"provider": provider})
        result = await builder.run(request)

        assert result.succeeded is False
        assert "No matches" in result.error

    async def test_a_model_cannot_keep_looping_on_tools(self, builder):
        provider = MockAIProvider(
            responses=[""], tool_calls=[ToolCall("documents", {"query": "x"})]
        )

        async def runner(skill, request):
            from jarvis2.core.models import SkillResult
            return SkillResult(succeeded=True, text="ok")

        builder.runner = runner
        request = Request(text="open x", metadata={"provider": provider})
        result = await builder.run(request)

        # Rather than let it go on, what it has is used.
        assert result.actions[0]["action"] == "tool_rounds_exceeded"


class TestDegradedMode:
    async def test_an_unreachable_provider_falls_back(self, settings, memory):
        from jarvis2.core.assistant import JarvisAssistant

        class Reader:
            def __init__(self):
                self.calls = []

            def resolve(self, query: str):
                from jarvis2.knowledge.wiki import Answer, Article

                self.calls.append(query)
                return Answer(
                    topic="einstein",
                    article=Article(
                        topic="einstein", title="Albert Einstein",
                        summary="A physicist.",
                        url="https://en.wikipedia.org/wiki/Albert_Einstein",
                    ),
                )

            def read_title(self, title: str, topic: str = ""):
                return self.resolve(title)

        reader = Reader()
        assistant = JarvisAssistant(
            settings=settings, memory=memory, wikipedia=reader,
            provider=failing())

        response = await assistant.handle_input("who is einstein", Source.TERMINAL)

        # The lookup still works; only the chatty part is lost.
        assert reader.calls == ["who is einstein"]
        assert response.text.startswith("Albert Einstein. ")
        assert "degraded" in response.metadata
        assert "without it" in response.metadata["degraded"]
