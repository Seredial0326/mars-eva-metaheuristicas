"""Convert paper/paper.md to paper/latex/paper.tex.

paper.md stays the source: edit it and run this script again.

    python paper/latex/md2tex.py

The converter only covers the Markdown that paper.md uses:
- front matter, headings, paragraphs, lists and pipe tables (with a bold "Table N." caption line);
- figures ![caption](figures/x.png){#fig:id} and references @fig:id;
- citations [@key; @key];
- inline and display math, kept as they are.

The bibliography is the "References" section of paper.md. Each entry is linked to its citation key
through REF_KEYS below.

Compile with pdflatex, from paper/latex/:

    pdflatex paper && pdflatex paper
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "paper.md"
OUT = HERE / "paper.tex"

# Citation key -> start of its entry in the "References" section of paper.md.
REF_KEYS = {
    "Allison2000": "Allison, M.",
    "Brady2019": "Brady, A. L.",
    "HiRISE-Gale": "Calef, F. J.",
    "Carr2003": "Carr, C. E.",
    "REMS-feed": "Centro de Astrobiolog",
    "Dorigo1997": "Dorigo, M.",
    "Gunawan2016": "Gunawan, A.",
    "RAD-L2": "Hassler, D. M. (PI)",
    "Hassler2014": "Hassler, D. M., Zeitlin",
    "Hausrath2026": "Hausrath, E. M.",
    "He2017": "He, K.",
    "HeldKarp1962": "Held, M.",
    "Herd2025": "Herd, C. D. K.",
    "Hinton2015": "Hinton, G.",
    "Irnich2005": "Irnich, S.",
    "Johnson2010": "Johnson, A. W.",
    "Kim2025": "Kim et al.",
    "Kirkpatrick1983": "Kirkpatrick, S.",
    "Marquez2019": "Marquez, J. J.",
    "Montemanni2009": "Montemanni, R.",
    "NASA-EMU": "NASA (2009)",
    "NASA-xEMU-met": "NASA (2022)",
    "NASA-Mars-mass": "NASA (2026)",
    "NASA-blog-4804": "NASA Curiosity blog",
    "MarsTrek": "NASA Solar System Treks",
    "JPL2026": "NASA/JPL (2026)",
    "MSL-raw": "NASA/JPL-Caltech",
    "VICAR-CAHVOR": "NASA-AMMOS",
    "Olofsson2014": "Olofsson, P.",
    "Pandolf1977": "Pandolf, K. B.",
    "Parker2016": "Parker, T. J.",
    "PyTorch": "Paszke, A.",
    "PLACES": "PDS Imaging Node",
    "ORTools": "Perron, L.",
    "Pflueger2019": "Pflueger, M.",
    "Prieur2023": "Prieur, N. C.",
    "Ronneberger2015": "Ronneberger, O.",
    "Santee2001": "Santee, W. R.",
    "Sato1998": "Sato, Y.",
    "Siebach2014": "Siebach, K. L. and Grotzinger",
    "Siebach2026": "Siebach, K. L. et al.",
    "Tan2019": "Tan, M.",
    "Tasgetiren2000": "Tasgetiren, M. F.",
    "THEMIS-night": "THEMIS team",
    "Tsiligirides1984": "Tsiligirides, T.",
    "Vansteenwegen2009": "Vansteenwegen, P., Souffriau, W., Vanden",
    "Vansteenwegen2011": "Vansteenwegen, P., Souffriau, W. and Van",
    "SciPy": "Virtanen, P.",
    "NASA-MarsFact": "Williams, D. R.",
    "Wu2019": "Wu, Y.",
    "Ziebart2008": "Ziebart, B. D.",
}

# Characters outside math, mapped to LaTeX that pdflatex understands. Longest first.
UNICODE = [
    ("g⊕", r"$g_\oplus$"), ("⁻¹", r"$^{-1}$"), ("⁻", r"$^{-}$"), ("¹", r"$^{1}$"), ("²", r"$^{2}$"),
    ("₂", r"$_{2}$"), ("–", "--"), ("—", "---"), ("·", r"$\cdot$"), ("°", r"$^\circ$"),
    ("×", r"$\times$"), ("−", r"$-$"), ("µ", r"$\mu$"), ("≈", r"$\approx$"), ("≤", r"$\le$"),
    ("≥", r"$\ge$"), ("→", r"$\rightarrow$"), ("α", r"$\alpha$"), ("θ", r"$\theta$"),
    ("τ", r"$\tau$"), ("σ", r"$\sigma$"), ("±", r"$\pm$"), ("√", r"$\surd$"), ("⊕", r"$\oplus$"),
    ("∎", r"$\blacksquare$"),
]
SPECIAL = {"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
           "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}

PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[margin=2.5cm]{geometry}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{array}
\usepackage{float}
\usepackage[hidelinks]{hyperref}
\usepackage{xurl}
\graphicspath{{../figures/}}
\setlength{\parskip}{0.4em}
"""


def protect(text, store):
    """Replace math, URLs and citations by placeholders so the text escaping leaves them alone."""
    def keep(s):
        store.append(s)
        return f"\x00{len(store) - 1}\x00"

    text = re.sub(r"\$\$(.+?)\$\$", lambda m: keep(r"\[" + m.group(1) + r"\]"), text, flags=re.S)
    text = re.sub(r"(?<!\\)\$(.+?)(?<!\\)\$", lambda m: keep("$" + m.group(1) + "$"), text)
    text = re.sub(r"\[(@[^\]]+)\]", lambda m: keep(r"\cite{" + ",".join(
        k.strip().lstrip("@") for k in m.group(1).split(";")) + "}"), text)
    text = re.sub(r"@fig:([\w-]+)", lambda m: keep(r"\ref{fig:" + m.group(1) + "}"), text)
    text = re.sub(r"https?://[^\s)]+[^\s).,;]", lambda m: keep(r"\url{" + m.group(0) + "}"), text)
    return text


def restore(text, store):
    return re.sub(r"\x00(\d+)\x00", lambda m: store[int(m.group(1))], text)


def inline(text):
    """Markdown inline -> LaTeX, for a run of text that may contain math."""
    store = []
    text = protect(text, store)
    text = re.sub(r"`([^`]+)`", lambda m: "\x01" + m.group(1) + "\x02", text)
    text = text.replace(r"\*", "\x03").replace(r"\|", "|")
    text = "".join(SPECIAL.get(c, c) for c in text)
    text = text.replace("\x03", "*")
    for a, b in UNICODE:
        text = text.replace(a, b)
    text = re.sub(r'"([^"]*)"', r"``\1''", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\emph{\1}", text)
    text = re.sub("\x01(.*?)\x02", r"\\texttt{\1}", text)
    text = text.replace("'", "'").replace("\u2019", "'")
    return restore(text, store)


def table(caption, rows):
    cells = [[c.strip() for c in re.split(r"(?<!\\)\|", r.strip().strip("|"))] for r in rows]
    head, body = cells[0], [c for c in cells[2:]]
    n = len(head)
    # Tables with long text wrap inside the page width; short, numeric tables keep natural
    # widths and are scaled down only when they have many columns.
    wrap = max(len(c) for row in cells for c in row) > 40
    env, spec = ("tabularx", r"{\linewidth}{" + r">{\raggedright\arraybackslash}X" * n + "}") if wrap \
        else ("tabular", "{" + "l" * n + "}")
    lines = [r"\begin{table}[H]", r"\centering\small"]
    if caption:
        lines.append(r"\caption{" + caption + "}")
    tab = [r"\begin{" + env + "}" + spec, r"\toprule",
           " & ".join(inline(h) for h in head) + r" \\", r"\midrule"]
    tab += [" & ".join(inline(c) for c in row) + r" \\" for row in body]
    tab += [r"\bottomrule", r"\end{" + env + "}"]
    if n > 4 and not wrap:
        lines.append(r"\resizebox{\linewidth}{!}{%")
        lines += tab
        lines.append("}")
    else:
        lines += tab
    lines.append(r"\end{table}")
    return "\n".join(lines)


def figure(line):
    m = re.match(r"!\[(.*)\]\(figures/([^)]+)\)(\{#(fig:[\w-]+)\})?", line.strip())
    cap, path, label = m.group(1), m.group(2), m.group(4)
    out = [r"\begin{figure}[H]", r"\centering",
           r"\includegraphics[width=\linewidth]{" + path + "}",
           r"\caption{" + inline(cap) + "}"]
    if label:
        out.append(r"\label{" + label + "}")
    out.append(r"\end{figure}")
    return "\n".join(out)


def bibliography(entries):
    items = []
    used = set()
    for entry in entries:
        keys = [k for k, start in REF_KEYS.items() if entry.startswith(start)]
        keys = [max(keys, key=lambda k: len(REF_KEYS[k]))] if keys else []
        if not keys:
            sys.exit(f"no citation key for reference: {entry[:60]}")
        used.add(keys[0])
        items.append(r"\bibitem{" + keys[0] + "} " + inline(entry))
    missing = set(REF_KEYS) - used
    if missing:
        sys.exit(f"keys without a reference entry: {sorted(missing)}")
    return "\n".join([r"\begin{thebibliography}{99}"] + items + [r"\end{thebibliography}"])


def convert(md):
    front, body = re.match(r"---\n(.*?)\n---\n(.*)", md, re.S).groups()
    meta = dict(re.findall(r'^(\w+):\s*"(.*)"\s*$', front, re.M))
    out = [PREAMBLE, r"\title{" + inline(meta["title"]) + "}",
           r"\author{" + inline(meta["author"]) + "}", r"\date{" + inline(meta["date"]) + "}",
           r"\begin{document}", r"\maketitle"]
    blocks = re.split(r"\n\s*\n", body.strip())
    in_abstract = in_refs = False
    refs, pending_caption = [], None
    cited = set(re.findall(r"@([A-Za-z0-9-]+)", body)) - {"fig"}
    unknown = cited - set(REF_KEYS)
    if unknown:
        sys.exit(f"citation keys not in REF_KEYS: {sorted(unknown)}")
    for block in blocks:
        first = block.splitlines()[0]
        if in_refs:
            refs.append(" ".join(block.split()))
            continue
        if first.startswith("## "):
            if in_abstract:
                out.append(r"\end{abstract}")
                in_abstract = False
            title = first[3:].strip()
            if title == "Abstract":
                out.append(r"\begin{abstract}")
                in_abstract = True
            elif title == "References":
                in_refs = True
            elif re.match(r"\d+\.\s", title):
                out.append(r"\section{" + inline(re.sub(r"^\d+\.\s*", "", title)) + "}")
            else:
                out.append(r"\section*{" + inline(title) + "}")
            rest = block.splitlines()[1:]
            if rest:
                blocks_rest = "\n".join(rest)
                out.append(inline(" ".join(blocks_rest.split())))
            continue
        if first.startswith("### "):
            title = re.sub(r"^\d+(\.\d+)*\s*", "", first[4:].strip())
            out.append(r"\subsection{" + inline(title) + "}")
            continue
        if first.startswith("!["):
            out.append(figure(first))
            continue
        lines = block.splitlines()
        if first.startswith("**Table"):
            cap_lines, table_lines = [], []
            for ln in lines:
                (table_lines if ln.startswith("|") else cap_lines).append(ln)
            raw = " ".join(" ".join(cap_lines).split())
            # LaTeX numbers the tables itself: drop the bold "Table N." prefix of the Markdown.
            raw = re.sub(r"^\*\*Table \d+\.\s*(.*?)\*\*", r"\1", raw)
            caption = inline(raw)
            if table_lines:
                out.append(table(caption, table_lines))
            else:
                pending_caption = caption
            continue
        if first.startswith("|"):
            out.append(table(pending_caption, lines))
            pending_caption = None
            continue
        if re.match(r"^(\d+\.|-)\s", first):
            env = "enumerate" if re.match(r"^\d+\.", first) else "itemize"
            items, cur = [], []
            for ln in lines:
                if re.match(r"^(\d+\.|-)\s", ln):
                    if cur:
                        items.append(" ".join(cur))
                    cur = [re.sub(r"^(\d+\.|-)\s+", "", ln)]
                else:
                    cur.append(ln.strip())
            items.append(" ".join(cur))
            out.append(r"\begin{" + env + "}")
            out += [r"\item " + inline(it) for it in items]
            out.append(r"\end{" + env + "}")
            continue
        out.append(inline(" ".join(block.split())))
    if in_abstract:
        out.append(r"\end{abstract}")
    out.append(bibliography(refs))
    out.append(r"\end{document}")
    tex = "\n\n".join(out) + "\n"
    leftover = sorted({c for c in re.sub(r"\\url\{[^}]*\}", "", tex) if ord(c) > 127} - set("éíáôöüàèñç"))
    if leftover:
        sys.exit(f"characters pdflatex may not handle: {leftover}")
    return tex


if __name__ == "__main__":
    OUT.write_text(convert(SRC.read_text(encoding="utf-8")), encoding="utf-8")
    print("wrote", OUT)
