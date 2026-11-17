%% sbpaper.cls -- working-paper class of the Sourcebound project template.
%%
%%   \documentclass[cite=authoryear]{sbpaper}      % cite = authoryear | numeric
%%                                                 % lang = british (default) | ngerman | ...
%%   \title{...}  \subtitle{Working Paper}  \author{...}  \date{...}
%%   \keywords{a; b}  \JEL{C12, G15}               % printed under the abstract
%%   \tablenote{...}                               % note below a table or figure
%%
%% Design: one serif family (TeX Gyre Termes via newtx), black text, citations in
%% blue, booktabs tables, no paragraph indentation, A4 with 25 mm margins.
\NeedsTeXFormat{LaTeX2e}[2022/11/01]
\ProvidesClass{sbpaper}[2026/11/09 v1.0 Sourcebound working paper]

\def\sb@cite{authoryear}
\def\sb@lang{british}
\DeclareKeys[sbpaper]{cite.store = \sb@cite, lang.store = \sb@lang}
\ProcessKeyOptions[sbpaper]
\LoadClass[11pt, a4paper]{article}

\RequirePackage[margin=25mm, headheight=14pt]{geometry}
\RequirePackage[T1]{fontenc}
\RequirePackage{amsmath, amsthm}
\RequirePackage{newtxtext, newtxmath}
\RequirePackage[varqu, scaled=0.95]{zi4}
\RequirePackage[final]{microtype}
\edef\sb@tmp{\noexpand\RequirePackage[\sb@lang]{babel}}\sb@tmp
\RequirePackage[autostyle]{csquotes}
\RequirePackage{xcolor, graphicx, booktabs, array, tabularx}
\RequirePackage[font=small, labelfont=bf, labelsep=period, skip=4pt]{caption}
\RequirePackage{parskip}
\RequirePackage{enumitem}
\setlist{itemsep=1pt, topsep=2pt, parsep=0pt}
\frenchspacing
\clubpenalty=10000 \widowpenalty=10000

\definecolor{sbcite}{RGB}{0,0,255}
\graphicspath{{figures/}{./}}

\def\sb@numeric{numeric}
\ifx\sb@cite\sb@numeric
  \RequirePackage[backend=biber, style=numeric-comp, sorting=none, maxbibnames=99,
    giveninits=true, isbn=false, eprint=false, url=true, doi=true, urldate=iso, seconds=true]{biblatex}
\else
  \RequirePackage[backend=biber, style=authoryear-comp, maxcitenames=2, maxbibnames=99,
    uniquelist=false, uniquename=false, giveninits=true, dashed=false, isbn=false,
    eprint=false, url=true, doi=true, urldate=iso, seconds=true]{biblatex}
\fi
\IfFileExists{references.bib}{\addbibresource{references.bib}}{}
\DeclareFieldFormat{doi}{\url{https://doi.org/#1}}
\DeclareFieldFormat{url}{\url{#1}}
\DeclareFieldFormat{urldate}{(accessed #1)}
\setcounter{biburlnumpenalty}{9000}
\setcounter{biburllcpenalty}{7000}
\setcounter{biburlucpenalty}{8000}

\RequirePackage{hyperref}
\hypersetup{colorlinks=true, linkcolor=black, urlcolor=black, filecolor=black,
  citecolor=sbcite, bookmarksnumbered=true, pdfdisplaydoctitle=true}
\urlstyle{same}
\RequirePackage[capitalise, noabbrev, nameinlink]{cleveref}
\AddToHook{begindocument/before}{\hypersetup{pdftitle={\@title}}}

%% Title block
\def\sb@subtitle{} \def\sb@keywords{} \def\sb@jel{}
\newcommand\subtitle[1]{\def\sb@subtitle{#1}}
\newcommand\keywords[1]{\def\sb@keywords{#1}\hypersetup{pdfkeywords={#1}}}
\newcommand\JEL[1]{\def\sb@jel{#1}}
\renewcommand\maketitle{%
  \begin{center}
    {\LARGE\bfseries\@title\par}%
    \ifx\sb@subtitle\@empty\else\vspace{4pt}{\large\sb@subtitle\par}\fi
    \vspace{10pt}{\large\@author\par}%
    \vspace{4pt}{\@date\par}%
  \end{center}
  \vspace{8pt}\let\thanks\@gobble\suppressfloats[t]}
\renewenvironment{abstract}
  {\small\list{}{\leftmargin=2.2em\rightmargin=\leftmargin}\item\relax
   \textbf{Abstract}\par\nobreak}
  {\par
   \ifx\sb@jel\@empty\else\vspace{3pt}\textbf{JEL classification:} \sb@jel\par\fi
   \ifx\sb@keywords\@empty\else\textbf{Keywords:} \sb@keywords\par\fi
   \endlist\vspace{6pt}}

%% Headings: bold serif, compact
\renewcommand\section{\@startsection{section}{1}{\z@}{-14pt plus -2pt}{6pt}{\normalfont\large\bfseries}}
\renewcommand\subsection{\@startsection{subsection}{2}{\z@}{-10pt plus -2pt}{4pt}{\normalfont\normalsize\bfseries}}

%% Note under a table or figure
\newcommand\tablenote[1]{\par\vspace{3pt}{\raggedright\footnotesize\textit{Note:} #1\par}}

\endinput
