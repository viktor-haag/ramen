"""Allowlist guard run before every LaTeX compile (spec 6.2).

Tectonic can read arbitrary paths, so documents (LLM-written or hand-edited)
are checked first. The raw text is scanned (comments are NOT stripped, TeX does
not treat `%` as a comment inside \\verb/\\url). Anything not known-safe or
present in the trusted template is a violation.
"""

import re
from dataclasses import dataclass

# Harmless text-formatting control words.
SAFE_COMMANDS = frozenset("""
begin end par newline linebreak pagebreak newpage clearpage noindent indent hfill vfill hspace vspace smallskip
medskip bigskip quad qquad enspace thinspace nobreakspace textbf textit textsl textsc textup texttt textrm textsf
textnormal emph underline bfseries itshape slshape scshape mdseries upshape normalfont rmfamily sffamily ttfamily
tiny scriptsize footnotesize small normalsize large Large LARGE huge Huge centering raggedright raggedleft item
today ldots dots textendash textemdash textbullet textquoteleft textquoteright textquotedblleft textquotedblright
guillemotleft guillemotright quotedblbase quotesinglbase euro ss ae AE oe OE aa AA o O l L i j copyright
textregistered texttrademark S P href url color textcolor LaTeX TeX
""".split())

SAFE_ENVIRONMENTS = frozenset(
    {"itemize", "enumerate", "description", "center", "flushleft", "flushright", "minipage", "quote"}
)

# Blocked by name even when the template uses them (except on identical template lines).
ALWAYS_FORBIDDEN = frozenset("""
input include InputIfFileExists IfFileExists openin read readline openout write immediate includegraphics
lstinputlisting verbatiminput inputminted pdffiledump filesize pdffilesize catcode csname scantokens makeatletter
ExplSyntaxOn UseName lastnamedcs begincsname special XeTeXpicfile XeTeXpdffile pdfximage bibliography verb
""".split())

# Preamble statements: must match a statement of the template (whitespace-insensitive).
# Value = number of mandatory {...} groups (an optional [...] may precede them).
PREAMBLE_COMMANDS = {
    "documentclass": 1,
    "usepackage": 1,
    "RequirePackage": 1,
    "RequirePackageWithOptions": 1,
    "LoadClass": 1,
    "LoadClassWithOptions": 1,
    "PassOptionsToPackage": 2,
    "PassOptionsToClass": 2,
}

FILECONTENTS = {"filecontents", "filecontents*"}

# `\begin` and `{X}` may be separated by whitespace, newlines and %-comments.
_BEGIN_RE = re.compile(r"\\begin(?![A-Za-z@])(?:\s|%[^\n]*)*\{([^}]*)\}")


@dataclass(frozen=True)
class Violation:
    command: str
    line: int  # 1-based


def _control_words(text: str) -> list[tuple[int, str]]:
    """Control words with position; `\\` + non-letter is a control symbol (skipped as a pair)."""
    out = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "\\":
            i += 1
            continue
        j = i + 1
        while j < n and (text[j].isascii() and text[j].isalpha() or text[j] == "@"):
            j += 1
        if j > i + 1:
            out.append((i, text[i + 1 : j]))
            i = j
        else:
            i += 2
    return out


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _group_end(text: str, i: int, opener: str) -> int:
    """Index after the balanced group starting at text[i] (EOF if unbalanced).

    `{...}` balances braces; `[...]` ends at the first `]` outside braces.
    """
    depth = 0
    n = len(text)
    j = i
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if opener == "{" and depth == 0:
                return j + 1
        elif c == "]" and opener == "[" and depth == 0:
            return j + 1
        j += 1
    return n


def _statements(text: str) -> list[tuple[int, str, str]]:
    """(position, command, whitespace-free statement text) for each preamble statement."""
    out = []
    for pos, name in _control_words(text):
        groups = PREAMBLE_COMMANDS.get(name)
        if groups is None:
            continue
        j = _skip_ws(text, pos + 1 + len(name))
        if j < len(text) and text[j] == "[":
            j = _group_end(text, j, "[")
        for _ in range(groups):
            j = _skip_ws(text, j)
            if j < len(text) and text[j] == "{":
                j = _group_end(text, j, "{")
        out.append((pos, name, re.sub(r"\s+", "", text[pos:j])))
    return out


def check(tex: str, template: str | None) -> Violation | None:
    """Return the earliest violation, or None if the document is allowed."""
    template = template or ""
    template_lines = {ln.strip() for ln in template.split("\n") if ln.strip()}
    allowed_words = SAFE_COMMANDS | {name for _, name in _control_words(template)}
    allowed_envs = SAFE_ENVIRONMENTS | {m.group(1) for m in _BEGIN_RE.finditer(template)}
    template_statements = {s for _, _, s in _statements(template)}

    hits: list[tuple[int, str]] = []

    for pos, name, stmt in _statements(tex):
        if stmt not in template_statements:
            hits.append((pos, "\\" + name))

    offset = 0
    for line in tex.split("\n"):
        if line.strip() not in template_lines:
            if "^^" in line:
                hits.append((offset + line.index("^^"), "^^"))
            for rel, name in _control_words(line):
                if name in PREAMBLE_COMMANDS:
                    continue  # handled as statement above
                if name in ALWAYS_FORBIDDEN or name not in allowed_words:
                    hits.append((offset + rel, "\\" + name))
        offset += len(line) + 1

    for m in _BEGIN_RE.finditer(tex):
        line_start = tex.rfind(chr(10), 0, m.start()) + 1
        line_end = tex.find(chr(10), m.start())
        first_line = tex[line_start : line_end if line_end >= 0 else len(tex)]
        if first_line.strip() in template_lines:
            continue
        env = m.group(1)
        if env.strip() in FILECONTENTS:
            hits.append((m.start(), "filecontents"))
        elif env not in allowed_envs:
            hits.append((m.start(), "\\begin{" + env + "}"))

    if not hits:
        return None
    pos, command = min(hits, key=lambda h: h[0])
    return Violation(command, tex.count("\n", 0, pos) + 1)
