import pytest

from app.latex.default_template import DEFAULT_TEMPLATE
from app.latex.guard import Violation, check, strip_comments

NL = chr(10)
BS = chr(92)


@pytest.mark.parametrize(
    "tex,command",
    [
        (r"\input{/data/x}", r"\input"),
        (r"\include{x}", r"\include"),
        (r"\InputIfFileExists{x}{}{}", r"\InputIfFileExists"),
        (r"\IfFileExists{x}{}{}", r"\IfFileExists"),
        (r"\openin1=x", r"\openin"),
        (r"\read1 to\x", r"\read"),
        (r"\readline", r"\readline"),
        (r"\openout", r"\openout"),
        (r"\write18{ls}", r"\write"),
        (r"\immediate", r"\immediate"),
        (r"\includegraphics{x}", r"\includegraphics"),
        (r"\lstinputlisting{x}", r"\lstinputlisting"),
        (r"\verbatiminput{x}", r"\verbatiminput"),
        (r"\inputminted{py}{x}", r"\inputminted"),
        (r"\pdffiledump", r"\pdffiledump"),
        (r"\filesize", r"\filesize"),
        (r"\pdffilesize", r"\pdffilesize"),
        (r"\catcode`\@=11", r"\catcode"),
        (r"\csname input\endcsname", r"\csname"),
        (r"\scantokens{x}", r"\scantokens"),
        (r"^^5cinput", "^^"),
        (r"\usepackage{verbatim}", "verbatim"),
        (r"\usepackage[x]{foo,Listings}", "listings"),
        (r"\RequirePackage{minted}", "minted"),
        (r"\usepackage{ pdfpages }", "pdfpages"),
        (r"\begin{filecontents*}{a}", "filecontents"),
        (r"\begin{filecontents}{a}", "filecontents"),
        (r"}\input{x}", r"\input"),
        (r"\input/etc/passwd", r"\input"),
        (r"50\% \input{x}", r"\input"),
    ],
)
def test_forbidden(tex, command):
    v = check(tex, None)
    assert v is not None
    assert v.command == command
    assert v.line == 1


@pytest.mark.parametrize(
    "tex",
    [
        r"\usepackage[utf8]{inputenc}",
        r"\writefoo",
        r"% \input{x}",
        r"\href{https://a.b/c\%20d}{x}",
        BS * 2 + r"% " + BS + "input{x}",
        r"\usepackage{hyperref,xcolor}",
    ],
)
def test_allowed(tex):
    assert check(tex, None) is None


def test_line_number():
    tex = NL.join(["a", "% c", r"\input{x}", ""])
    assert check(tex, None) == Violation(r"\input", 3)


def test_line_number_multiline_package():
    tex = NL.join(["a", r"\usepackage{", "foo,", "minted}"])
    assert check(tex, None) == Violation("minted", 2)


def test_strip_comments_keeps_lines():
    src = NL.join(["a % c", r"b\% d", BS * 2 + "% e", "f"])
    assert strip_comments(src) == NL.join(["a ", r"b\% d", BS * 2, "f"])


def test_template_exception():
    tpl = NL.join([r"\documentclass{x}", r"  \catcode`\@=11 % c", ""])
    assert check("\t" + r"\catcode`\@=11", tpl) is None
    assert check(r"\catcode`\@=12", tpl) is not None
    assert check(r"\catcode`\@=11", None) is not None


def test_default_template_passes():
    assert check(DEFAULT_TEMPLATE, None) is None
