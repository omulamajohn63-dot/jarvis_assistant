"""What happens when somebody asks for a file, a folder or an app.

Driven through the one entry point every interface uses, and only asserting on
what came back and what was really opened. A dispatcher that records the open
is checked first, so a test asserting "nothing was opened" cannot pass because
the open failed quietly.
"""

from pathlib import Path

import pytest

from jarvis2.core.assistant import JarvisAssistant
from jarvis2.core.models import Source


class Recorder(JarvisAssistant):
    """An assistant that remembers what it opened instead of opening it.

    The path is checked here exactly once, by recording it, and nothing else:
    each skill has already decided whether the path is one it may touch before
    it gets here. Re-checking in the double would test the double.
    """

    def __init__(self, *args, **kwargs):
        self.opened: list = []
        self.visited: list = []
        super().__init__(*args, **kwargs)

    def _open_path(self, path: str) -> None:
        self.opened.append(path)


class Apps:
    """A stand-in for the Start Menu, so no real program is measured."""

    def __init__(self, entries=None):
        self.entries = dict(entries or {
            "Chrome": r"C:\Program Files\Chrome\chrome.exe",
            "Firefox": r"C:\Program Files\Firefox\firefox.exe",
            "Firefox Private Browsing": r"C:\Program Files\Firefox\private.exe",
            "Visual Studio Code": r"C:\Users\me\AppData\Local\Programs\Code\Code.exe",
        })

    def __call__(self):
        return self.entries


@pytest.fixture
def assistant(settings, memory, home, monkeypatch):
    from jarvis2.skills import applications

    monkeypatch.setattr(applications, "installed_shortcuts", Apps())
    return Recorder(settings=settings, memory=memory)


def home_of(settings) -> Path:
    return Path(settings.extra["root"])


class TestApplications:
    @pytest.mark.parametrize("phrase", [
        "open chrome", "launch chrome", "start chrome", "run chrome",
        "please open chrome", "could you open chrome",
        "hey jarvis open chrome", "open the chrome",
    ])
    async def test_every_way_of_asking_opens_the_same_program(self, assistant, phrase):
        await assistant.handle_input(phrase, Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert "chrome" in assistant.opened[0].lower()

    async def test_the_shortest_name_wins(self, assistant):
        # Both are installed, and "Firefox Private Browsing" must not be what
        # "open firefox" means.
        await assistant.handle_input("open firefox", Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert assistant.opened[0].endswith("Firefox\\firefox.exe")

    async def test_a_program_windows_ships_with_is_found(self, assistant):
        # Notepad has no Start Menu shortcut, so the only way to find it is the
        # PATH. It lives in System32, which the path rules protect from a path
        # somebody typed and allow for a program the assistant looked up.
        await assistant.handle_input("open notepad", Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert assistant.opened[0].lower().endswith("notepad.exe")

    @pytest.mark.parametrize("phrase,expected", [
        ("open vs code", "Code.exe"),
        ("open code", "Code.exe"),
    ])
    async def test_an_alias_finds_the_program(self, assistant, phrase, expected,
                                              monkeypatch):
        from jarvis2.skills import applications

        # The PATH is searched before the Start Menu by design, so what this
        # machine happens to have installed would decide the answer. Emptying
        # it leaves the alias mapping as the only thing under test.
        monkeypatch.setattr(applications, "_from_path", lambda _name: None)

        await assistant.handle_input(phrase, Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert assistant.opened[0].endswith(expected)

    async def test_a_program_that_is_not_installed_is_named(self, assistant):
        response = await assistant.handle_input("open nonesuchapp", Source.TERMINAL)

        assert assistant.opened == []
        assert "nonesuchapp" in response.text.lower()

    async def test_a_typo_is_still_found(self, assistant, monkeypatch):
        from jarvis2.skills import applications

        # Nothing on the PATH under that name, so only a near miss in the Start
        # Menu can save it.
        monkeypatch.setattr(applications, "_from_path", lambda _name: None)

        await assistant.handle_input("open chrom", Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert "chrome" in assistant.opened[0].lower()


class TestFolders:
    @pytest.mark.parametrize("phrase,folder", [
        ("open downloads", "Downloads"),
        ("open music", "Music"),
        ("open videos", "Videos"),
        ("open pictures", "Pictures"),
        ("open images", "Pictures"),
        ("open desktop", "Desktop"),
        ("open documents", "Documents"),
        ("open docs", "Documents"),
        ("open the music folder", "Music"),
    ])
    async def test_a_folder_is_found_by_name_or_by_alias(self, settings, assistant,
                                                         phrase, folder):
        target = home_of(settings) / folder
        target.mkdir(parents=True, exist_ok=True)

        await assistant.handle_input(phrase, Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert Path(assistant.opened[0]) == target

    async def test_a_folder_that_is_not_there_is_not_invented(self, home,
                                                               assistant):
        import shutil

        shutil.rmtree(home / "Music")

        await assistant.handle_input("open music", Source.TERMINAL)

        assert assistant.opened == []

    async def test_a_drive_letter_that_is_not_there_is_not_invented(self, assistant):
        await assistant.handle_input("open z:", Source.TERMINAL)

        assert assistant.opened == []


class TestWebsites:
    async def test_a_known_site_is_browsed(self, assistant, monkeypatch):
        import webbrowser

        visited = []
        monkeypatch.setattr(webbrowser, "open", lambda url: visited.append(url))

        await assistant.handle_input("open youtube", Source.TERMINAL)

        assert visited and "youtube" in visited[0]
        assert assistant.opened == []

    async def test_a_site_is_not_mistaken_for_a_file(self, settings, assistant,
                                                     monkeypatch):
        # "YouTube" begins with "you", which used to count as naming a document,
        # so "open youtube" opened an unrelated Word file.
        import webbrowser

        for folder, name in (
            ("Documents", "youtube notes.docx"),
            ("Music", "YouTube download.mp3"),
        ):
            path = home_of(settings) / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 64)

        visited = []
        monkeypatch.setattr(webbrowser, "open", lambda url: visited.append(url))

        await assistant.handle_input("open youtube", Source.TERMINAL)

        assert visited and "youtube" in visited[0]
        assert assistant.opened == []


class TestMedia:
    @pytest.fixture
    def library(self, settings):
        for folder, name in (
            ("Music", "Oh Jah.mp3"),
            ("Music", "COLLOBLUE - TOP SHOTTA FT KBC.mp3"),
            ("Videos", "Blues Brothers.mp4"),
        ):
            path = home_of(settings) / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 64)

    async def test_a_song_is_found_and_opened(self, settings, assistant, library):
        await assistant.handle_input("play oh jah", Source.TERMINAL)

        assert assistant.opened == [str(home_of(settings) / "Music" / "Oh Jah.mp3")]

    async def test_a_spaced_out_title_still_matches(self, settings, assistant,
                                                    library):
        await assistant.handle_input("play collo blue top shotta", Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert "COLLOBLUE" in assistant.opened[0]

    async def test_a_video_is_found(self, settings, assistant, library):
        await assistant.handle_input("watch blues brothers", Source.TERMINAL)

        assert assistant.opened == [
            str(home_of(settings) / "Videos" / "Blues Brothers.mp4")]

    async def test_a_request_naming_nothing_in_particular_asks(self, assistant,
                                                               library):
        response = await assistant.handle_input("play something", Source.TERMINAL)

        assert assistant.opened == []
        assert response.text

    async def test_a_song_that_is_not_there_is_named(self, assistant, library):
        response = await assistant.handle_input("play nosuchsong", Source.TERMINAL)

        assert assistant.opened == []
        assert "nosuchsong" in response.text.lower()


class TestDocuments:
    @pytest.fixture
    def library(self, settings):
        for folder, name in (
            ("Documents", "Curriculum Vitae.pdf"),
            ("Documents", "CV Template.docx"),
            ("Downloads", "CV Final.pdf"),
        ):
            path = home_of(settings) / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"0" * 2048)

    async def test_several_matches_are_listed_rather_than_one_being_opened(
        self, settings, assistant, library
    ):
        response = await assistant.handle_input("open my cv", Source.TERMINAL)

        # Opening one of three would be a guess.
        assert assistant.opened == []
        assert len(response.choices) >= 2

    async def test_the_number_opens_the_row_carrying_it(self, settings, assistant,
                                                        library):
        listed = await assistant.handle_input("open my cv", Source.TERMINAL)

        await assistant.handle_input("2", Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert assistant.opened[0] == listed.choices[1].payload

    async def test_reading_does_not_open_a_window(self, settings, assistant,
                                                   library):
        path = home_of(settings) / "Documents" / "syllabus.txt"
        path.write_text("UNIT 1 Introduction to office automation", encoding="utf-8")

        await assistant.handle_input("read my syllabus", Source.TERMINAL)

        assert assistant.opened == []

    async def test_opening_does_not_read_the_document_out(self, settings, assistant,
                                                           library):
        path = home_of(settings) / "Documents" / "syllabus.txt"
        path.write_text("UNIT 1 Introduction to office automation", encoding="utf-8")

        response = await assistant.handle_input("open my syllabus", Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert "office automation" not in response.text.lower()

    async def test_an_open_matching_no_document_falls_through_to_an_app(
        self, settings, assistant
    ):
        # "open chrome" matches no document, and the assistant must not stop
        # there having found nothing.
        await assistant.handle_input("open chrome", Source.TERMINAL)

        assert len(assistant.opened) == 1
        assert "chrome" in assistant.opened[0].lower()
