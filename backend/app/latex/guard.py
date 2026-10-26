"""Forbidden-command guard run before every LaTeX compile (spec 6.2).

Tectonic can read arbitrary paths, so documents (LLM-written or hand-edited)
are scanned for file access, obfuscation and risky packages first.
"""

import re
from dataclasses import dataclass

FORBIDDEN_COMMANDS = (
    "input", "include", "InputIfFileExists", "IfFileExists", "openin", "read",
    "readline", "openout", "write", "immediate", "includegraphics",
    "lstinputlisting", "verbatiminput", "inputminted", "pdffiledump",
    "filesize", "pdffilesize", "catcode", "csname", "scantokens",
)
FORBIDDEN_PACKAGES = frozenset({
    "verbatim", "listings", "minted", "shellesc", "catchfile", "bashful",
    "pythontex", "fancyvrb", "moreverb", "filecontents", "attachfile",
    "embedfile", "pdfpages",
})

_COMMAND_RE = re.compile(
    r"\\(" + "|".join(sorted(FORBIDDEN_COMMANDS, key=len, reverse=True)) + r")(?![A-Za-z@])"
)
_PACKAGE_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}"
)
_FILECONTENTS_RE = re.compile(r"\\begin\s*\{filecontents\*?\}")


@dataclass(frozen=True)
class Violation:
    command: str
    line: int  # 1-based, line in the original document


def strip_comments(tex: str) -> str:
    r"""Remove `%` to end of line (not `\%`); the number of lines is kept."""
    out = []
    for line in tex.split("\n"):
        i = 0
        while i < len(line):
            c = line[i]
            if c == "\\":
                i += 2  # skip the escaped character (`\%`, `\\`)
                continue
            if c == "%":
                line = line[:i]
                break
            i += 1
        out.append(line)
    return "\n".join(out)


def _find_all(text: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for m in _COMMAND_RE.finditer(text):
        hits.append((m.start(), "\\" + m.group(1)))
    for m in re.finditer(r"\^\^", text):
        hits.append((m.start(), "^^"))
    for m in _PACKAGE_RE.finditer(text):
        for name in m.group(1).split(","):
            if name.strip().lower() in FORBIDDEN_PACKAGES:
                hits.append((m.start(), name.strip().lower()))
    for m in _FILECONTENTS_RE.finditer(text):
        hits.append((m.start(), "filecontents"))
    hits.sort(key=lambda h: h[0])
    return hits


def check(tex: str, template: str | None) -> Violation | None:
    """Return the first violation, or None if the document is clean."""
    text = strip_comments(tex)
    lines = text.split("\n")
    allowed: set[str] = set()
    if template is not None:
        allowed = {ln.strip() for ln in strip_comments(template).split("\n")}
    for pos, command in _find_all(text):
        line_no = text.count("\n", 0, pos) + 1
        if lines[line_no - 1].strip() in allowed:
            continue
        return Violation(command, line_no)
    return None
