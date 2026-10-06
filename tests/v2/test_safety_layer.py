"""The safety layer: risk, paths, permissions and confirmations.

These are the tests that matter most. They are what stop a change, in this
repository or a future one, from making the assistant do something nobody asked
for.
"""

import os
from pathlib import Path

import pytest

from jarvis2.safety import paths, permissions, policy
from jarvis2.safety.confirmations import ConfirmationManager
from jarvis2.safety.policy import Risk


class TestRiskTable:
    @pytest.mark.parametrize("action", [
        "tell_time", "open_application", "open_website", "take_screenshot",
        "search_files", "read_document", "tell_joke",
    ])
    def test_harmless_actions_are_low(self, action):
        assert policy.classify(action) is Risk.LOW

    @pytest.mark.parametrize("action", [
        "move_file", "rename_file", "change_setting", "close_application",
    ])
    def test_actions_that_change_something_are_medium(self, action):
        assert policy.classify(action) is Risk.MEDIUM

    @pytest.mark.parametrize("action", [
        "delete_file", "delete_folder", "shutdown", "restart", "format_drive",
        "execute_command", "edit_registry", "change_security_setting",
    ])
    def test_actions_that_lose_data_are_high(self, action):
        assert policy.classify(action) is Risk.HIGH

    def test_an_action_nobody_declared_is_treated_as_high(self):
        # Guessing low would mean a new skill was trusted by default, which is
        # the mistake worth refusing.
        assert policy.classify("something_nobody_declared") is Risk.HIGH

    def test_an_undeclared_action_is_not_allowed(self):
        decision = policy.evaluate("something_nobody_declared")
        assert decision.allowed is False

    def test_running_a_command_is_never_allowed(self):
        decision = policy.evaluate("execute_command", "rm -rf /")
        assert decision.allowed is False

    def test_every_action_has_a_description(self):
        for name, action in policy.POLICY.items():
            assert action.description, name

    def test_the_counts(self):
        counts = policy.risk_counts()
        assert sum(counts.values()) == len(policy.POLICY)


class TestConfirmationIsNotOptional:
    @pytest.mark.parametrize("action", [
        "delete_file", "shutdown", "restart", "format_drive", "edit_registry",
    ])
    def test_high_risk_always_asks(self, action):
        # Even with confirmation turned off. A setting that turned this off
        # would be a setting that let one mistaken answer shut down a computer.
        assert policy.needs_confirmation(action, confirm_dangerous=False) is True

    @pytest.mark.parametrize("action", ["tell_time", "open_application",
                                        "open_website", "take_screenshot"])
    def test_low_risk_does_not_ask(self, action):
        assert policy.needs_confirmation(action) is False

    def test_medium_risk_asks_only_when_asked_to(self):
        assert policy.needs_confirmation("move_file") is False
        assert policy.needs_confirmation("move_file", confirm_medium=True) is True

    def test_the_prompt_names_what_will_happen(self):
        action = policy.describe("delete_file", "C:/Users/me/cv.pdf")
        prompt = policy.prompt_for(action)
        assert "C:/Users/me/cv.pdf" in prompt
        assert "delete" in prompt.lower()

    def test_a_prompt_says_so_when_it_cannot_be_undone(self):
        # The power actions have their own wording, which is clearer than the
        # generic one, so an action that falls through to the generic branch is
        # what this checks.
        assert "cannot be undone" in policy.prompt_for(
            policy.describe("edit_registry", "HKLM\\Software")
        )
        assert "cannot be undone" in policy.prompt_for(
            policy.describe("format_drive", "E:")
        )


class TestPathResolution:
    def test_a_relative_path_is_made_absolute(self, tmp_path):
        resolved = paths.resolve("cv.pdf", base=tmp_path)
        assert resolved.is_absolute()

    def test_dot_dot_is_collapsed(self, home):
        # A path that looks like it is in Downloads must not climb out of it.
        escape = home / "Downloads" / ".." / ".." / "Windows" / "cmd.exe"
        resolved = paths.resolve(str(escape))
        assert ".." not in str(resolved)

    def test_quotes_are_stripped(self):
        assert '"' not in str(paths.resolve('"C:/Users/me/cv.pdf"'))

    def test_an_empty_path_is_refused(self):
        verdict = paths.validate("")
        assert verdict.allowed is False

    def test_whitespace_only_is_refused(self):
        assert paths.validate("   ").allowed is False

    def test_tilde_is_expanded(self):
        assert "~" not in str(paths.resolve("~/cv.pdf"))


class TestProtectedDirectories:
    @pytest.mark.parametrize("path", [
        r"C:\Windows", r"C:\Windows\System32",
        r"C:\Program Files", r"C:\Program Files (x86)",
        r"C:\ProgramData", r"C:\$Recycle.Bin", r"C:\Recovery",
    ])
    def test_windows_is_protected(self, path):
        assert paths.is_protected(path) is True

    @pytest.mark.parametrize("path", [
        r"C:\Windows\System32", r"C:\Windows\explorer.exe",
    ])
    def test_anything_under_windows_is_protected(self, path):
        assert paths.is_protected(path) is True

    def test_a_user_folder_is_not_protected(self, home):
        assert paths.is_protected(str(home / "Downloads")) is False

    def test_validate_refuses_it(self):
        verdict = paths.validate(r"C:\Windows\notepad.exe")
        assert verdict.allowed is False
        assert "system directory" in verdict.reason


class TestProgramsAreNotDocuments:
    @pytest.mark.parametrize("name", [
        "setup.exe", "run.bat", "script.ps1", "thing.lnk", "page.vbs",
    ])
    def test_refused(self, name):
        # Whether or not the file exists: a path is checked before it is touched,
        # so a missing file must not be a way past this.
        verdict = paths.validate(f"C:/tmp/{name}", expect="document")
        assert verdict.allowed is False
        assert "program" in verdict.reason

    @pytest.mark.parametrize("name", ["notes.pdf", "cv.docx", "data.csv",
                                      "song.mp3"])
    def test_real_documents_are_fine(self, name):
        assert paths.validate(f"C:/tmp/{name}", expect="document").allowed is True

    def test_a_file_is_not_a_folder(self, home):
        path = home / "Documents" / "cv.pdf"
        path.write_bytes(b"0")
        verdict = paths.validate(str(path), expect="folder")
        assert verdict.allowed is False
        assert "not a folder" in verdict.reason


class TestDeleting:
    def test_a_document_may_go(self, home):
        assert paths.is_safe_to_delete(str(home / "Documents" / "cv.pdf")) is True

    def test_a_download_may_go(self, home):
        assert paths.is_safe_to_delete(str(home / "Downloads" / "a.txt")) is True

    def test_a_temporary_file_may_go(self, tmp_path):
        scratch = Path(os.environ.get("TEMP", str(tmp_path))) / "scratch.txt"
        assert paths.is_safe_to_delete(str(scratch)) is True

    def test_a_named_folder_may_not_go(self, home):
        # Deleting a file called Documents\cv.pdf is ordinary. Deleting
        # Documents itself is not, and the two must not be confused.
        assert paths.is_safe_to_delete(str(home / "Documents")) is False

    def test_the_home_directory_may_not_go(self, home):
        assert paths.is_safe_to_delete(str(home)) is False

    @pytest.mark.parametrize("path", ["C:/", "C:\\Windows",
                                      "C:/Windows/System32"])
    def test_system_places_may_not_go(self, path):
        assert paths.is_safe_to_delete(path) is False

    def test_nonsense_is_refused(self):
        assert paths.is_safe_to_delete("") is False


class TestDisplay:
    def test_a_home_path_is_shortened(self, home):
        assert paths.display(str(home / "Documents" / "cv.pdf")) == (
            "~/Documents/cv.pdf"
        )

    def test_a_system_path_is_left_alone(self):
        # A system path must not be cut down to nonsense.
        assert paths.display(r"C:\Windows\notepad.exe") == "C:/Windows/notepad.exe"

    def test_the_home_directory_itself(self, home):
        assert paths.display(str(home)) == "~"


class TestPermissions:
    def test_low_risk_actions_are_permitted(self):
        allowed = permissions.default_permissions()
        assert allowed.permits("open_application") is True
        assert allowed.permits("tell_time") is True

    def test_running_a_command_is_not_permitted(self):
        # Structurally refused, so declaring a skill for it is an error.
        assert permissions.default_permissions().permits("execute_command") is False

    def test_an_undeclared_action_is_not_permitted(self):
        assert permissions.default_permissions().permits("nonsense") is False

    def test_require_rejects_an_unknown_name(self):
        with pytest.raises(permissions.PermissionError_, match="unknown"):
            permissions.require(permissions.default_permissions(), ["nonsense"])

    def test_require_rejects_a_denied_action(self):
        with pytest.raises(permissions.PermissionError_):
            permissions.require(
                permissions.default_permissions(), ["execute_command"]
            )

    def test_require_accepts_a_permitted_action(self):
        permissions.require(permissions.default_permissions(), ["open_application"])

    def test_an_action_can_be_turned_off(self):
        allowed = permissions.default_permissions().without("open_application")
        assert allowed.permits("open_application") is False

    def test_an_action_can_be_turned_on(self):
        allowed = permissions.default_permissions().with_actions("move_file")
        assert allowed.permits("move_file") is True

    def test_highest_risk(self):
        assert permissions.highest_risk(["tell_time", "delete_file"]) is Risk.HIGH
        assert permissions.highest_risk(["tell_time"]) is Risk.LOW
        assert permissions.highest_risk([]) is Risk.LOW


class TestConfirmationManager:
    @pytest.fixture
    def manager(self):
        return ConfirmationManager()

    async def test_asking_holds_the_action(self, manager):
        ran = []
        confirmation = manager.ask(
            policy.describe("shutdown"), lambda: ran.append("yes") or "done"
        )
        # Nothing has happened yet.
        assert ran == []
        assert confirmation.risk == "high"
        assert confirmation.prompt

    async def test_approving_runs_it(self, manager):
        ran = []
        confirmation = manager.ask(
            policy.describe("shutdown"), lambda: ran.append("yes") or "done"
        )
        ok, result = await manager.resolve(confirmation.id, True)
        assert ok is True
        assert ran == ["yes"]
        assert result == "done"

    async def test_declining_does_not(self, manager):
        ran = []
        confirmation = manager.ask(
            policy.describe("shutdown"), lambda: ran.append("yes")
        )
        ok, message = await manager.resolve(confirmation.id, False)
        assert ok is False
        assert ran == []
        assert "not do that" in message

    async def test_an_unknown_id_runs_nothing(self, manager):
        ran = []
        manager.ask(policy.describe("shutdown"), lambda: ran.append("yes"))
        ok, message = await manager.resolve("nonsense", True)
        assert ok is False
        assert ran == []

    async def test_a_stale_id_runs_nothing(self, manager):
        ran = []
        first = manager.ask(policy.describe("shutdown"),
                            lambda: ran.append("first"))
        await manager.resolve(first.id, False)
        manager.ask(policy.describe("restart"), lambda: ran.append("second"))

        # The old id cannot approve whatever is waiting now.
        ok, _message = await manager.resolve(first.id, True)
        assert ok is False
        assert ran == []

    async def test_the_same_id_cannot_be_replayed(self, manager):
        ran = []
        confirmation = manager.ask(policy.describe("shutdown"),
                                    lambda: ran.append("yes"))
        first, _ = await manager.resolve(confirmation.id, True)
        second, _ = await manager.resolve(confirmation.id, True)
        assert first is True
        assert second is False
        assert ran == ["yes"]

    async def test_an_async_action_is_awaited(self, manager):
        ran = []

        async def carry_out():
            ran.append("yes")
            return "done"

        confirmation = manager.ask(policy.describe("shutdown"), carry_out)
        ok, result = await manager.resolve(confirmation.id, True)
        assert ok is True
        assert ran == ["yes"]
        assert result == "done"

    async def test_each_question_gets_its_own_id(self, manager):
        first = manager.ask(policy.describe("shutdown"), lambda: None)
        await manager.resolve(first.id, False)
        second = manager.ask(policy.describe("shutdown"), lambda: None)
        assert second.id != first.id

    async def test_pending_shows_the_waiting_question(self, manager):
        assert manager.pending is None
        confirmation = manager.ask(policy.describe("delete_file"), lambda: None)
        assert manager.pending.id == confirmation.id

    async def test_the_arguments_cannot_change_between_asking_and_answering(self,
                                                                     manager):
        # The callable is stored with the question, so nothing can be edited
        # into it while the user is reading it.
        detail = {"target": "C:/Users/me/cv.pdf"}
        confirmation = manager.ask(
            policy.describe("delete_file"), lambda: detail, details=detail
        )
        detail["target"] = "C:/Windows"
        assert confirmation.details["target"] == "C:/Users/me/cv.pdf"

    async def test_a_refusal_can_say_why(self, manager):
        said = []
        confirmation = manager.ask(policy.describe("shutdown"), lambda: None)
        _ok, message = await manager.resolve(
            confirmation.id, False, reject=lambda: said.append(message := "no")
        )
        assert said == ["no"]

    async def test_history_records_the_answers(self, manager):
        confirmation = manager.ask(policy.describe("shutdown"), lambda: None)
        await manager.resolve(confirmation.id, True)
        history = manager.history
        assert history[-1]["approved"] is True
        assert history[-1]["action"] == "shutdown"

    def test_a_low_risk_action_is_not_held(self, manager):
        # The action runs straight away, so nothing is stored to answer.
        confirmation = manager.evaluate_and_ask(
            "open_application", "C:/chrome.lnk", run=lambda: "opened"
        )
        assert confirmation is None
        assert manager.pending is None

    def test_a_high_risk_action_is_held(self, manager):
        ran = []
        confirmation = manager.evaluate_and_ask(
            "delete_file", "C:/cv.pdf", run=lambda: ran.append("yes")
        )
        assert confirmation is not None
        assert ran == []

    def test_an_action_the_policy_refuses_raises(self, manager):
        with pytest.raises(PermissionError):
            manager.evaluate_and_ask(
                "execute_command", "rm -rf /", run=lambda: None
            )
