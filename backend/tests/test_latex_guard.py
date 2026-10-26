import pytest

from app.latex.default_template import DEFAULT_TEMPLATE
from app.latex.guard import Violation, check

NL = chr(10)

# Bypasses found in review of the old denylist design; all must be blocked.
POCS = [
    r"\csname@@input\endcsname /etc/passwd ",
    r"\verb|%| \input{/etc/passwd}",
    r"\url{x%}\input{/etc/passwd}",
    r"\usepackage{catch file}\CatchFileDef\x{/etc/passwd}{}\x",
    r"\def\p{catchfile}\usepackage{\p}",
    r"\usepackage[x={]}]{catchfile}",
    r"\RequirePackageWithOptions{catchfile}",
    r"\makeatletter\@@input /etc/passwd \makeatother",
    r"\UseName{input}{/etc/passwd}",
    r"\ExplSyntaxOn \file_get:nnN {/etc/passwd} {} \l_tmpa_tl \ExplSyntaxOff",
    r"\ExplSyntaxOn \use:c {input} {/etc/passwd} \ExplSyntaxOff",
    r'\XeTeXpdffile "/data/x.pdf" ',
    r'\XeTeXpicfile "/data/x.png" ',
    r"\special{pdf:fstream @f (/etc/passwd)}",
    r"\documentclass{/abs/x}",
    r"\usepackage{/abs/path}",
    r"\bibliography{/abs/x}",
]


@pytest.mark.parametrize("tex", POCS)
@pytest.mark.parametrize("template", [None, DEFAULT_TEMPLATE])
def test_poc_blocked(tex, template):
    assert check(tex, template) is not None


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
        (r"\usepackage{verbatim}", r"\usepackage"),
        (r"\RequirePackage{minted}", r"\RequirePackage"),
        (r"\begin{filecontents*}{a}", "filecontents"),
        (r"\begin{filecontents}{a}", "filecontents"),
        (r"\begin{verbatim}", r"\begin{verbatim}"),
        (r"}\input{x}", r"\input"),
        (r"\input/etc/passwd", r"\input"),
        (r"\foo", r"\foo"),
        (r"\inputenc", r"\inputenc"),
        (r"\writefoo", r"\writefoo"),
    ],
)
def test_blocked_without_template(tex, command):
    v = check(tex, None)
    assert v is not None
    assert v.command == command
    assert v.line == 1


def test_commented_input_is_blocked_because_raw_scan():
    # Comments are not stripped: TeX does not treat % as a comment inside \verb/\url.
    assert check(r"% \input{x}", None) == Violation(r"\input", 1)


@pytest.mark.parametrize(
    "tex",
    [
        r"\textbf{a} \emph{b} \\ c",
        r"50\% \href{https://a.b/c\%20d}{x}",
        r"\begin{itemize}" + NL + r"\item a" + NL + r"\end{itemize}",
        "Müller äöüß",
        r"\\input is just a line break and text",
    ],
)
def test_safe_text_allowed(tex):
    assert check(tex, None) is None


def test_line_number():
    tex = NL.join(["a", "b", r"\input{x}", ""])
    assert check(tex, None) == Violation(r"\input", 3)


def test_default_template_against_itself():
    assert check(DEFAULT_TEMPLATE, DEFAULT_TEMPLATE) is None


def test_filled_in_letter_allowed():
    letter = (
        DEFAULT_TEMPLATE.replace("{John}{Doe}", "{Erika}{Mustermann}")
        .replace("Random LLC", "Beispiel GmbH")
        .replace(
            "Opening paragraph: the position and why you are writing.",
            r"ich bewerbe mich als \textbf{Entwickler} bei Beispiel GmbH. "
            r"Ihre Anzeige (siehe \href{https://a.b/c\%20d}{x}) hat mich "
            r"\emph{begeistert}; Müller sagt: 50\% Erfolg.",
        )
        .replace("Street 1 \\\\ 12345 City", "Straße 1 \\\\ 80331 München")
    )
    assert letter != DEFAULT_TEMPLATE
    assert check(letter, DEFAULT_TEMPLATE) is None


def test_unknown_command_allowed_when_template_uses_it():
    tpl = r"\newcommand{\foo}{x}"
    assert check(r"\foo", None) == Violation(r"\foo", 1)
    assert check(r"\foo", tpl) is None


def test_forbidden_command_blocked_even_if_template_uses_it_elsewhere():
    tpl = NL.join([r"\documentclass{article}", r"\input{x}", ""])
    assert check(r"\input{y}", tpl) == Violation(r"\input", 1)
    assert check("  " + r"\input{x}", tpl) is None


def test_usepackage_must_match_template():
    tpl = NL.join([r"\documentclass{article}", r"\usepackage{xcolor}", ""])
    assert check(r"\usepackage{xcolor}", tpl) is None
    assert check(r"\usepackage{ xcolor }", tpl) is None
    assert check(r"\usepackage{xcolor,catchfile}", tpl) == Violation(r"\usepackage", 1)
    assert check(r"\usepackage{xcolor}", None) == Violation(r"\usepackage", 1)


def test_multiline_usepackage_statement():
    tpl = NL.join([r"\usepackage{xcolor,", "  hyperref}", ""])
    same = r"\usepackage{xcolor, hyperref}"
    assert check(same, tpl) is None
    changed = NL.join(["a", r"\usepackage{xcolor,", "  catchfile}"])
    assert check(changed, tpl) == Violation(r"\usepackage", 2)


def test_environments():
    assert check(r"\begin{itemize}", None) is None
    assert check(r"\begin{verbatim}", None) == Violation(r"\begin{verbatim}", 1)
    assert check(r"\begin{filecontents*}{a}", None) == Violation("filecontents", 1)
    assert check(r"\begin{minipage}", None) is None
    tpl = r"\begin{tabular}{ll}"
    assert check(r"\begin{tabular}{ll}", tpl) is None
