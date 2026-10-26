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
    assert f.visible == "Hi "
    f.feed(" more</think> there")
    assert f.visible == "Hi  there"


def test_partial_think_tag_held_back():
    f = fed("Hi <th")
    assert f.visible == "Hi "
    f.feed("e end")
    assert f.visible == "Hi <the end"


def test_opening_fence_line_removed():
    assert fed("```latex\n\\doc").visible == "\\doc"
    assert fed("``", "`latex\n\\doc").visible == "\\doc"


def test_fence_line_incomplete_shows_nothing_yet():
    assert fed("```lat").visible == ""


def test_no_hold_back_for_unrelated_tail():
    assert fed("Dear team,").visible == "Dear team,"


def test_reset_clears():
    f = fed("Hallo")
    f.reset()
    assert f.visible == ""
    f.feed("Neu")
    assert f.visible == "Neu"
