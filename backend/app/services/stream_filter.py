"""Visible part of a streamed cover-letter answer (the letter only, never the note or `<think>` blocks).

The answer format: the document, then a line containing only `NOTE_MARKER`, then the note. `visible`
is recomputed from the whole raw text on every `feed` (letters are small), so split tags/markers are
handled without state machines: characters that could still turn into a marker, a `<think>` tag or a
code fence are held back until it is clear they do not. Invariant: every `visible` is a prefix of the
document that `cover_letter_llm.parse_answer` finally extracts (it uses `strip_think`/`strip_fences`).
"""
import re

NOTE_MARKER = "<<<RAMEN-NOTE>>>"

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_TAG = "<think>"
_FENCE = "```"
_OPEN_FENCE = re.compile(r"```[A-Za-z]*[ \t]*\r?\n")


def strip_think(text: str) -> str:
    """Remove complete `<think>` blocks; an unclosed `<think>` cuts off the rest."""
    text = _THINK_BLOCK.sub("", text)
    m = _THINK_OPEN.search(text)
    return text[: m.start()] if m else text


def strip_fences(document: str) -> str:
    """Remove an opening code-fence line and, if there was one, a closing fence at the end."""
    document = document.strip()
    m = _OPEN_FENCE.match(document)
    if m:
        document = document[m.end():].rstrip()
        if document.endswith(_FENCE):
            document = document[: -len(_FENCE)]
    return document.strip()


def _hold_think_tag(text: str) -> str:
    low = text[-len(_THINK_TAG):].lower()
    for n in range(min(len(low), len(_THINK_TAG) - 1), 0, -1):  # a started `<think>` tag at the end
        if _THINK_TAG.startswith(low[-n:]):
            return text[:-n]
    return text


def _cut_marker(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == NOTE_MARKER:
            return "\n".join(lines[:i])
    if NOTE_MARKER.startswith(lines[-1].lstrip()):  # the last line might still become the marker line
        return "\n".join(lines[:-1])
    return text


def visible_text(raw: str) -> str:
    text = _hold_think_tag(strip_think(raw)).lstrip()
    fenced = False
    if text.startswith(_FENCE):
        m = _OPEN_FENCE.match(text)
        if m:
            text, fenced = text[m.end():], True
        elif "\n" not in text:  # the fence line is not complete yet
            return ""
    elif _FENCE.startswith(text):  # might still become an opening fence
        return ""
    text = _cut_marker(text)
    if fenced:  # a (partial) closing fence at the end is not part of the document
        text = text.rstrip().rstrip("`")
    return text.rstrip()  # trailing whitespace (incl. `\r`) is stripped from the final document too


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
