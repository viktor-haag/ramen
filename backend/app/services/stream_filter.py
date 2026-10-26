"""Visible part of a streamed cover-letter answer (the letter only, never the note or `<think>` blocks).

The answer format: the document, then a line containing only `NOTE_MARKER`, then the note. `visible`
is recomputed from the whole raw text on every `feed` (letters are small), so split tags/markers are
handled without state machines: characters that could still turn into a marker or `<think>` tag are
held back until it is clear they do not.
"""
import re

NOTE_MARKER = "<<<RAMEN-NOTE>>>"

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_TAG = "<think>"
_FENCE = "```"


def _hide_think(text: str) -> str:
    text = _THINK_BLOCK.sub("", text)
    m = _THINK_OPEN.search(text)
    if m:
        return text[: m.start()]
    low = text[-len(_THINK_TAG):].lower()
    for n in range(min(len(low), len(_THINK_TAG) - 1), 0, -1):  # a started `<think>` tag at the end
        if _THINK_TAG.startswith(low[-n:]):
            return text[:-n]
    return text


def _drop_fence_line(text: str) -> str:
    head = text.lstrip()
    if head.startswith(_FENCE):
        nl = text.find("\n")
        return "" if nl < 0 else text[nl + 1:]
    if head and _FENCE.startswith(head):  # might still become an opening fence line
        return ""
    return text


def _cut_marker(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == NOTE_MARKER:
            return "\n".join(lines[:i])
    last = lines[-1].lstrip()
    if NOTE_MARKER.startswith(last):  # the last line might still become the marker line
        return "\n".join(lines[:-1])
    return text


def visible_text(raw: str) -> str:
    return _cut_marker(_drop_fence_line(_hide_think(raw)))


class StreamFilter:
    def __init__(self) -> None:
        self._raw: list[str] = []
        self._visible = ""

    def feed(self, chunk: str) -> None:
        self._raw.append(chunk)
        self._visible = visible_text("".join(self._raw))

    def reset(self) -> None:
        self._raw.clear()
        self._visible = ""

    @property
    def visible(self) -> str:
        return self._visible
