"""Reading a document out loud.

Everything here is about what the user is told. A document that was only partly
read has to say so, and a document that could not be read has to be opened
instead of quietly answering with nothing.
"""

import pytest

from jarvis2.core.models import Request, Source
from jarvis2.files import documents
from jarvis2.skills import build_default_registry


class TestPlainText:
    def test_a_markdown_file_comes_back_as_it_is(self, tmp_path):
        # Byte for byte. A file that is written to be read should not be
        # rewritten on its way to the reader.
        source = "# Title\n\nSome words."
        path = tmp_path / "notes.md"
        path.write_text(source, encoding="utf-8")

        assert documents.read(str(path)) == source

    def test_one_bad_byte_does_not_fail_the_whole_read(self, tmp_path):
        # Real files have an encoding somebody chose badly. One of them must not
        # take the assistant down.
        path = tmp_path / "mixed.txt"
        path.write_bytes(b"good \xff\xfe bytes")

        text = documents.read(str(path))

        assert "good" in text


class TestRtf:
    def test_the_control_words_are_stripped(self, tmp_path):
        # Read as it stands, the codes would be spoken aloud as noise.
        path = tmp_path / "unit.rtf"
        path.write_text(r"{\rtf1\ansi Unit 1 Introduction}")

        text = documents.read(str(path))

        assert "Unit 1 Introduction" in text
        assert "rtf1" not in text
        assert "{" not in text


class TestTheReaderRegistry:
    @pytest.mark.parametrize("extension", [
        ".txt", ".md", ".csv", ".log", ".rtf", ".pdf", ".docx", ".pptx",
        ".xlsx", ".xlsm",
    ])
    def test_every_format_we_promise_can_be_read(self, extension):
        assert documents.can_read(f"report{extension}") is True

    @pytest.mark.parametrize("extension", [".doc", ".xls", ".ppt"])
    def test_the_pre_2007_formats_have_no_reader(self, extension):
        # These are opened rather than read, which is the honest answer: saying
        # a file was read when nothing came of it would be worse than opening it.
        assert documents.can_read(f"report{extension}") is False
        assert extension in documents.UNREADABLE

    def test_an_unknown_extension_yields_no_text_rather_than_an_error(self, tmp_path):
        path = tmp_path / "thing.xyz"
        path.write_bytes(b"whatever")

        assert documents.read(str(path)) == ""

    def test_a_reader_that_fails_yields_no_text(self, tmp_path):
        path = tmp_path / "broken.txt"
        path.write_text("fine", encoding="utf-8")

        original = documents.READERS[".txt"]
        documents.READERS[".txt"] = lambda _p: (_ for _ in ()).throw(
            RuntimeError("broken file"))
        try:
            assert documents.read(str(path)) == ""
        finally:
            documents.READERS[".txt"] = original


class TestWhatIsSpoken:
    def test_whitespace_is_collapsed(self, tmp_path):
        # Documents are full of line breaks and runs of spaces, and a reader
        # pausing on every one of them sounds broken.
        path = tmp_path / "syllabus.txt"
        path.write_text("one\n\n\n   two\t\tthree", encoding="utf-8")

        spoken, truncated = documents.prepare(str(path))

        assert spoken == "one two three"
        assert truncated is False

    def test_a_long_document_is_cut_and_says_so(self, tmp_path):
        path = tmp_path / "long.txt"
        path.write_text("word " * 5000, encoding="utf-8")

        spoken, truncated = documents.prepare(str(path))

        assert truncated is True
        assert len(spoken) <= documents.READ_CHAR_LIMIT

    def test_the_limit_is_honoured_when_one_is_given(self, tmp_path):
        path = tmp_path / "long.txt"
        path.write_text("word " * 5000, encoding="utf-8")

        spoken, truncated = documents.prepare(str(path), limit=40)

        assert len(spoken) <= 40
        assert truncated is True

    def test_an_empty_document_yields_nothing_to_say(self, tmp_path):
        path = tmp_path / "blank.txt"
        path.write_text("   \n\n  ", encoding="utf-8")

        spoken, truncated = documents.prepare(str(path))

        assert spoken == ""
        assert truncated is False

    def test_a_file_that_is_not_there_yields_nothing(self, tmp_path):
        spoken, truncated = documents.prepare(str(tmp_path / "gone.txt"))

        assert spoken == ""
        assert truncated is False


class TestAskingForADocument:
    """The skill's side: what it says, and what it hands to Windows."""

    async def test_an_empty_document_is_named_as_unreadable(self, home, context):
        (home / "Documents" / "blank.txt").write_text("   ", encoding="utf-8")

        skill = build_default_registry().get("documents")

        result = await skill.perform(
            "read", "blank", context, Request(text="read blank", source=Source.TERMINAL))

        assert result.succeeded is False
        assert "could not find any text" in result.text
    async def test_a_document_that_is_not_there_is_not_claimed(self, home, context):
        skill = build_default_registry().get("documents")

        result = await skill.perform(
            "read", "nosuchdoc", context,
            Request(text="read nosuchdoc", source=Source.TERMINAL))

        # The name is repeated back so the user can hear which document was
        # meant, and nothing is claimed to have been read or opened.
        assert result.succeeded is False
        assert "nosuchdoc" in result.text
        assert result.opened == []

    async def test_an_unreadable_format_is_said_out_loud_and_still_opened(
        self, home, context
    ):
        # Refusing to read a .doc and saying nothing would leave the user with
        # no document and no explanation. Saying it cannot be read, and then
        # opening it, does both.
        (home / "Documents" / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0")

        skill = build_default_registry().get("documents")
        result = await skill.perform(
            "read", "old", context, Request(text="read old", source=Source.TERMINAL))

        assert result.succeeded is True
        assert "DOC" in result.text
        assert len(context.opened) == 1
        assert context.opened[0].endswith("old.doc")

    async def test_a_document_that_is_not_there_is_named_in_the_reply(
        self, home, context
    ):
        skill = build_default_registry().get("documents")

        request = Request(text="read nosuchdoc", source=Source.TERMINAL)
        result = await skill.perform("read", "nosuchdoc", context, request)

        assert "could not find" in result.text.lower()
        assert context.opened == []
