import pytest

from app.services.cover_letter_llm import parse_answer
from app.services.stream_filter import NOTE_MARKER, StreamFilter


def fed(*chunks: str) -> StreamFilter:
    f = StreamFilter()
    for c in chunks:
        f.feed(c)
    return f


def test_marker_split_across_chunks_never_shows():
    f = StreamFilter()
    f.feed("Hallo\n<<<RAMEN-")
    assert "<<<" not in f.visible and f.visible.startswith("Hallo")
    f.feed("NOTE>>>\nNotiz")
    assert f.visible == "Hallo"


def test_held_back_characters_appear_once_disambiguated():
    f = StreamFilter()
    f.feed("Text\n<<<")
    assert "<<<" not in f.visible
    f.feed(" nein")
    assert f.visible == "Text\n<<< nein"


def test_marker_with_whitespace_and_later_text_hidden():
    assert fed("Brief\n  ", NOTE_MARKER, "  \nNotiz\nmehr").visible == "Brief"


def test_marker_at_start():
    assert fed(NOTE_MARKER + "\nNotiz").visible == ""


def test_marker_inside_a_line_is_text():
    assert fed("a <<<RAMEN-NOTE>>> b c d e f g h i j k l m n o p").visible == (
        "a <<<RAMEN-NOTE>>> b c d e f g h i j k l m n o p"
    )


def test_think_split_across_chunks():
    assert fed("<thi", "nk>x</think>Hi").visible == "Hi"


def test_open_think_hides_rest():
    f = fed("Hi <think>secret")
    assert f.visible == "Hi"
    f.feed(" more</think> there")
    assert f.visible == "Hi  there"


def test_partial_think_tag_held_back():
    f = fed("Hi <th")
    assert f.visible == "Hi"
    f.feed("e end")
    assert f.visible == "Hi <the end"


def test_opening_fence_line_removed():
    assert fed("```latex\n\\doc").visible == "\\doc"
    assert fed("``", "`latex\n\\doc").visible == "\\doc"


def test_fence_line_incomplete_shows_nothing_yet():
    assert fed("```lat").visible == ""


def test_no_hold_back_for_unrelated_tail():
    assert fed("Dear team,").visible == "Dear team,"


def test_fence_after_think_and_leading_whitespace():
    raw = "<think>plan</think>\n\n```latex\n\\documentclass{a}\n\\end{document}\n```\n<<<RAMEN-NOTE>>>\nn"
    assert fed(raw).visible == "\\documentclass{a}\n\\end{document}"
    assert fed("\n```latex\nX").visible == "X"
    assert fed("  \nDear").visible == "Dear"


def test_closing_fence_hidden():
    assert fed("```latex\nX\n```").visible == "X"
    assert fed("```latex\nX\n``").visible == "X"
    assert fed("```\nX```").visible == "X"


def test_crlf_marker():
    assert fed("Hallo\r\n<<<RAMEN-NOTE>>>\r\nNotiz").visible == "Hallo"


ANSWERS = [
    "<think>plan</think>\n\n```latex\n\\documentclass{a}\n\\begin{document}\nHi ``quoted''\n\\end{document}\n```\n"
    "<<<RAMEN-NOTE>>>\nn",
    "Sehr geehrte Damen und Herren,\r\n\r\nich bewerbe mich.\r\n\r\nMit freundlichen Grüßen\r\n<<<RAMEN-NOTE>>>\r\n"
    "Telefon fehlt.",
    "Dear team,\n\nI <think>hmm</think>apply.  \n\nRegards\n  <<<RAMEN-NOTE>>>  \nnote",
    "```\nDear team,\nText with a <<<RAMEN-NOTE>>> inline.\n```\n<<<RAMEN-NOTE>>>\nnote",
    "```latex\n\\documentclass{a}\n\\begin{document}\nX\n\\end{document}```\n<<<RAMEN-NOTE>>>\nn",
    "Dear team,\nshort letter <3.\n",
    "A\n<<<RAMEN-NOTE>>>\nB\n<<<RAMEN-NOTE>>>\nnote",
    "<THINK>x</THINK>Hello `code` and <b> tags\n<<<RAMEN-NOTE>>>",
]


@pytest.mark.parametrize("answer", ANSWERS)
def test_char_by_char_snapshots_are_growing_prefixes_of_the_parsed_document(answer):
    document, _ = parse_answer(answer, "text")
    f, previous = StreamFilter(), ""
    for ch in answer:
        f.feed(ch)
        assert document.startswith(f.visible), (f.visible, document)
        assert f.visible.startswith(previous), (previous, f.visible)
        previous = f.visible
    first_marker_cut = document.split("\n<<<RAMEN-NOTE>>>")[0]
    assert f.visible == first_marker_cut


def test_reset_clears():
    f = fed("Hallo")
    f.reset()
    assert f.visible == ""
    f.feed("Neu")
    assert f.visible == "Neu"
