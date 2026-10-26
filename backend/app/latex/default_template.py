"""Built-in cover letter template (Deedy, cleaned up): plain LaTeX, compiles with Tectonic."""

DEFAULT_TEMPLATE_NAME = "Deedy"

DEFAULT_TEMPLATE = r"""\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[scaled]{helvet}
\renewcommand{\familydefault}{\sfdefault}
\usepackage[a4paper,margin=2.5cm]{geometry}
\usepackage{xcolor}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}

\definecolor{subtle}{HTML}{666666}
\setlength{\parindent}{0pt}

\pagestyle{fancy}
\fancyhf{}
\rfoot{\thepage}
\renewcommand{\headrulewidth}{0pt}

\newcommand{\namesection}[3]{%
  \begin{center}
    {\fontsize{32pt}{36pt}\selectfont #1 \textbf{#2}}\\[6pt]
    {\small\color{subtle}#3}
  \end{center}
  \vspace{4pt}\hrule\vspace{14pt}}
\newcommand{\companyname}[1]{\textbf{#1}\\}
\newcommand{\companyaddress}[1]{#1}
\newcommand{\currentdate}[1]{\hfill #1}
\newcommand{\lettercontent}[1]{#1\par\medskip}
\newcommand{\closing}[1]{\par\bigskip #1\par}
\newcommand{\signature}[1]{\vspace{1.5cm}#1}

\begin{document}
\thispagestyle{empty}

\namesection{John}{Doe}{%
  \href{https://johndoe.xyz}{johndoe.xyz} |
  \href{mailto:me@johndoe.xyz}{me@johndoe.xyz} |
  0777 1238921 |
  \href{https://github.com}{GitHub} |
  \href{https://linkedin.com}{LinkedIn}}

\begin{minipage}[t]{0.5\textwidth}
\companyname{Random LLC}
\companyaddress{Street 1 \\ 12345 City}
\end{minipage}%
\begin{minipage}[t]{0.5\textwidth}
\currentdate{\today}
\end{minipage}

\bigskip
\lettercontent{Dear Recruiter,}

\lettercontent{Opening paragraph: the position and why you are writing.}
\lettercontent{Main paragraph: what you bring, backed by evidence.}
\lettercontent{Second main paragraph: further matches with the posting.}
\lettercontent{Closing paragraph: thanks and next steps.}

\closing{Sincerely,}
\signature{John Doe}

\end{document}
"""
