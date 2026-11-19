"""The drawings: one source for the landing page, the guide and the README.

Each figure is a viewBox, a one-sentence label and an SVG body written against a few class names (`box`, `edge`,
`t`, `mut`, `mono`, `acc`, `hi`, `dash`, `soft`, `rod`, `grey`, `viol`, `well`). `inline()` gives the body for an
HTML page, where the site's stylesheet colours those classes from its tokens, so a figure follows the page's theme and
its toggle. `standalone()` gives a self-contained SVG document with the same classes styled inline in the site's
light values and, under `prefers-color-scheme: dark`, its dark ones, on an opaque card, for Markdown viewers such as
GitHub that show an SVG as an image. `write()` puts those files under docs/guide/figures/, and `--check` says whether
the files there are the ones this module makes, so a test can keep them current. Zero dependencies, like the tool.

    python3 tools/figures.py            # writes docs/guide/figures/*.svg
    python3 tools/figures.py --check    # exit 1 when a file there is stale or missing
"""

from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "guide" / "figures"


@dataclass(frozen=True)
class Figure:
    viewbox: str
    label: str  # one sentence a reader without the picture gets instead
    body: str  # the SVG elements, classed
    kind: str = ""  # "chart" draws narrower on a phone


# The values are the site's tokens (site/tessri.css); the standalone files cannot reach them, so they carry copies.
LIGHT = {"ink": "#17151e", "ink2": "#4e4863", "muted": "#7b7590", "line": "#e0dcf0", "panel": "#ffffff", "well": "#f0eef8", "accent": "#5544b4"}
DARK = {"ink": "#f0eef6", "ink2": "#c1bacf", "muted": "#8b86a0", "line": "#2b2842", "panel": "#151222", "well": "#171424", "accent": "#b0a0ff"}
SANS = 'Inter, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
MONO = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace'


def _rules(t: dict[str, str]) -> str:
    return (
        f"svg{{color:{t['ink2']}}}"
        f"text{{font-family:{SANS};font-size:12px;fill:{t['ink2']}}}"
        f".t{{font-size:13.5px;font-weight:500;fill:{t['ink']}}}"
        f".mut{{font-size:11px;fill:{t['muted']}}}"
        f".mono{{font-family:{MONO};font-size:11.5px}}"
        f".acc{{font-size:15px;font-weight:600;fill:{t['accent']}}}"
        f".box{{fill:{t['panel']};stroke:{t['ink2']};stroke-width:1.1}}"
        f".hi{{stroke:{t['accent']};stroke-width:1.6}}"
        f".edge{{fill:none;stroke:{t['ink2']};stroke-width:1.1}}"
        ".dash{stroke-dasharray:4 4}"
        f".soft{{stroke:{t['line']}}}"
        f".rod{{stroke:{t['line']};stroke-width:2}}"
        f".grey{{fill:{t['muted']};stroke:{t['panel']};stroke-width:2}}"
        f".viol{{fill:{t['accent']};stroke:{t['panel']};stroke-width:2}}"
        f".well{{fill:{t['well']}}}"
        f".bg{{fill:{t['panel']}}}"
    )


FIGURES: dict[str, Figure] = {
    "layer": Figure(
        viewbox="0 0 880 220",
        kind="",
        label="""An agent or a person writes a change. Tessri reads the code and its git history, offline, and hands the person who stands behind the code four answers: where to look first, who can look, what changed in the structure, what nobody maintains.""",
        body="""<defs><marker id="arrow-a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="currentColor"/></marker></defs>
<rect class="box" x="20" y="60" width="176" height="100" rx="8"/>
<text class="t" x="108" y="104" text-anchor="middle">An agent, or a person</text>
<text class="mut" x="108" y="126" text-anchor="middle">writes a change</text>
<line class="edge" x1="196" y1="110" x2="288" y2="110" marker-end="url(#arrow-a)"/>
<text class="mut" x="242" y="100" text-anchor="middle">a change</text>
<rect class="box hi" x="290" y="30" width="290" height="160" rx="10"/>
<text class="acc" x="435" y="68" text-anchor="middle">Tessri</text>
<text x="435" y="94" text-anchor="middle">reads the code and its git history</text>
<text class="mut" x="435" y="116" text-anchor="middle">offline · no model · zero dependencies</text>
<text class="mut" x="435" y="136" text-anchor="middle">never edits the code</text>
<text class="mut" x="435" y="168" text-anchor="middle">every line traceable with <tspan class="mono">tessri why</tspan></text>
<line class="edge" x1="580" y1="62" x2="688" y2="62" marker-end="url(#arrow-a)"/>
<line class="edge" x1="580" y1="97" x2="688" y2="97" marker-end="url(#arrow-a)"/>
<line class="edge" x1="580" y1="132" x2="688" y2="132" marker-end="url(#arrow-a)"/>
<line class="edge" x1="580" y1="167" x2="688" y2="167" marker-end="url(#arrow-a)"/>
<text x="634" y="54" text-anchor="middle">where to look first</text>
<text x="634" y="89" text-anchor="middle">who can look</text>
<text x="634" y="124" text-anchor="middle">what changed in the structure</text>
<text x="634" y="159" text-anchor="middle">what nobody maintains</text>
<rect class="box" x="690" y="40" width="172" height="150" rx="8"/>
<text class="t" x="776" y="106" text-anchor="middle">The person who</text>
<text class="t" x="776" y="124" text-anchor="middle">stands behind it</text>
<text class="mut" x="776" y="150" text-anchor="middle">reviews · maintains · decides</text>
      """,
    ),
    "pipeline": Figure(
        viewbox="0 0 980 300",
        kind="",
        label="""The files go through inventory, the analyzers for Python and JavaScript with the names found in configs and docs, and the graph, into one analysis; the git history goes through gitlog and ownership into the same analysis; scan, why, graph, impact, triage, check and brief are views of it; the cache sits beside the analyzers.""",
        body="""<defs><marker id="arrow-b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="currentColor"/></marker></defs>
<rect class="box" x="10" y="100" width="96" height="46" rx="6"/>
<text class="t" x="58" y="120" text-anchor="middle">Repository</text>
<text class="mut" x="58" y="138" text-anchor="middle">files · git</text>
<line class="edge" x1="106" y1="123" x2="138" y2="123" marker-end="url(#arrow-b)"/>
<rect class="box" x="140" y="100" width="108" height="46" rx="6"/>
<text class="mono" x="194" y="120" text-anchor="middle">inventory</text>
<text class="mut" x="194" y="138" text-anchor="middle">files, languages, lines</text>
<path class="edge" d="M248 123 C266 123 266 73 282 73" marker-end="url(#arrow-b)"/>
<path class="edge" d="M248 123 C266 123 266 173 282 173" marker-end="url(#arrow-b)"/>
<rect class="box" x="284" y="50" width="144" height="46" rx="6"/>
<text class="mono" x="356" y="70" text-anchor="middle">textrefs</text>
<text class="mut" x="356" y="88" text-anchor="middle">names in configs, CI, docs</text>
<rect class="box" x="284" y="150" width="144" height="46" rx="6"/>
<text class="mono" x="356" y="170" text-anchor="middle">analyzers</text>
<text class="mut" x="356" y="188" text-anchor="middle">python · javascript</text>
<line class="edge dash" x1="356" y1="196" x2="356" y2="236"/>
<text class="mut" x="364" y="220">reads, keeps</text>
<rect class="box dash" x="284" y="236" width="144" height="46" rx="6"/>
<text class="mono" x="356" y="256" text-anchor="middle">cache</text>
<text class="mut" x="356" y="274" text-anchor="middle">by content, in your cache dir</text>
<path class="edge" d="M428 73 C448 73 448 123 466 123" marker-end="url(#arrow-b)"/>
<path class="edge" d="M428 173 C448 173 448 123 466 123" marker-end="url(#arrow-b)"/>
<rect class="box" x="468" y="100" width="96" height="46" rx="6"/>
<text class="mono" x="516" y="120" text-anchor="middle">graph</text>
<text class="mut" x="516" y="138" text-anchor="middle">entries and tests as roots</text>
<line class="edge" x1="564" y1="123" x2="598" y2="123" marker-end="url(#arrow-b)"/>
<rect class="box" x="600" y="100" width="96" height="46" rx="6"/>
<text class="mono" x="648" y="120" text-anchor="middle">analyze</text>
<text class="mut" x="648" y="138" text-anchor="middle">one record per file</text>
<line class="edge" x1="696" y1="123" x2="730" y2="123" marker-end="url(#arrow-b)"/>
<rect class="box hi" x="732" y="100" width="104" height="46" rx="6"/>
<text class="acc" x="784" y="120" text-anchor="middle">Analysis</text>
<text class="mut" x="784" y="138" text-anchor="middle">one picture</text>
<path class="edge" d="M58 146 L58 292 L516 292 L516 284" marker-end="url(#arrow-b)"/>
<rect class="box" x="464" y="236" width="104" height="46" rx="6"/>
<text class="mono" x="516" y="256" text-anchor="middle">gitlog</text>
<text class="mut" x="516" y="274" text-anchor="middle">history, up to a rev</text>
<line class="edge" x1="568" y1="259" x2="598" y2="259" marker-end="url(#arrow-b)"/>
<rect class="box" x="600" y="236" width="96" height="46" rx="6"/>
<text class="mono" x="648" y="256" text-anchor="middle">ownership</text>
<text class="mut" x="648" y="274" text-anchor="middle">who maintains what</text>
<line class="edge" x1="648" y1="236" x2="648" y2="148" marker-end="url(#arrow-b)"/>
<path class="edge" d="M836 123 C856 123 856 42 870 42" marker-end="url(#arrow-b)"/>
<path class="edge" d="M836 123 C856 123 856 98 870 98" marker-end="url(#arrow-b)"/>
<path class="edge" d="M836 123 C856 123 856 154 870 154" marker-end="url(#arrow-b)"/>
<path class="edge" d="M836 123 C856 123 856 210 870 210" marker-end="url(#arrow-b)"/>
<path class="edge" d="M836 123 C856 123 856 266 870 266" marker-end="url(#arrow-b)"/>
<rect class="box" x="872" y="24" width="100" height="36" rx="6"/>
<text class="mono" x="922" y="46" text-anchor="middle">scan · why</text>
<rect class="box" x="872" y="80" width="100" height="36" rx="6"/>
<text class="mono" x="922" y="102" text-anchor="middle">graph · impact</text>
<rect class="box" x="872" y="136" width="100" height="36" rx="6"/>
<text class="mono" x="922" y="158" text-anchor="middle">triage</text>
<rect class="box" x="872" y="192" width="100" height="36" rx="6"/>
<text class="mono" x="922" y="214" text-anchor="middle">check</text>
<rect class="box" x="872" y="248" width="100" height="36" rx="6"/>
<text class="mono" x="922" y="270" text-anchor="middle">brief</text>
      """,
    ),
    "backtest": Figure(
        viewbox="0 0 780 214",
        kind="chart",
        label="""On three repositories' history, Tessri's order of the changed files predicts a fix within 30 days better than ordering by the size of the change: nemo-rl 0.79 against 0.52, pytest 0.64 against 0.54, vuejs/core 0.66 against 0.57, as AUC where 0.5 is random.""",
        body="""<circle class="grey" cx="262" cy="22" r="5"/><text x="274" y="26">largest diff first</text>
<circle class="viol" cx="414" cy="22" r="5"/><text x="426" y="26">Tessri's order: commits in 90 days, then size</text>
<line class="edge dash soft" x1="344" y1="52" x2="344" y2="186"/>
<text class="mut" x="344" y="46" text-anchor="middle">random 0.50</text>
<line class="soft" x1="250" y1="188" x2="730" y2="188"/>
<text class="mut" x="344" y="206" text-anchor="middle">0.5</text>
<text class="mut" x="438" y="206" text-anchor="middle">0.6</text>
<text class="mut" x="532" y="206" text-anchor="middle">0.7</text>
<text class="mut" x="626" y="206" text-anchor="middle">0.8</text>
<text class="mut" x="730" y="206" text-anchor="end">AUC</text>
<text x="236" y="80" text-anchor="end">nemo-rl · large, squashed</text>
<line class="rod" x1="363" y1="76" x2="617" y2="76"/>
<circle class="grey" cx="363" cy="76" r="6"/><circle class="viol" cx="617" cy="76" r="6"/>
<text class="mut" x="352" y="80" text-anchor="end">0.52</text><text x="628" y="80">0.79</text>
<text x="236" y="120" text-anchor="end">pytest · small, merge commits</text>
<line class="rod" x1="382" y1="116" x2="476" y2="116"/>
<circle class="grey" cx="382" cy="116" r="6"/><circle class="viol" cx="476" cy="116" r="6"/>
<text class="mut" x="371" y="120" text-anchor="end">0.54</text><text x="487" y="120">0.64</text>
<text x="236" y="160" text-anchor="end">vuejs/core · TypeScript monorepo</text>
<line class="rod" x1="410" y1="156" x2="494" y2="156"/>
<circle class="grey" cx="410" cy="156" r="6"/><circle class="viol" cx="494" cy="156" r="6"/>
<text class="mut" x="399" y="160" text-anchor="end">0.57</text><text x="505" y="160">0.66</text>
      """,
    ),
    "loop": Figure(
        viewbox="0 0 980 268",
        kind="",
        label="""Six stations in a loop: arriving in a project with scan, graph and why; before a change, impact; while the agent edits, hooks give impact after each edit and check when it stops; review with triage; done with check; hand over with brief as a pull request comment; then back to the start.""",
        body="""<defs><marker id="arrow-c" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="currentColor"/></marker></defs>
<text class="mut" x="90" y="76" text-anchor="middle">a person</text>
<text class="mut" x="250" y="76" text-anchor="middle">a person, or an agent</text>
<text class="mut" x="410" y="76" text-anchor="middle">the agent, through hooks</text>
<text class="mut" x="570" y="76" text-anchor="middle">a person</text>
<text class="mut" x="730" y="76" text-anchor="middle">CI, or a person</text>
<text class="mut" x="890" y="76" text-anchor="middle">person to person</text>
<rect class="box" x="22" y="88" width="136" height="56" rx="8"/><text class="t" x="90" y="121" text-anchor="middle">Arriving</text>
<rect class="box" x="182" y="88" width="136" height="56" rx="8"/><text class="t" x="250" y="121" text-anchor="middle">Before a change</text>
<rect class="box" x="342" y="88" width="136" height="56" rx="8"/><text class="t" x="410" y="121" text-anchor="middle">While it is made</text>
<rect class="box" x="502" y="88" width="136" height="56" rx="8"/><text class="t" x="570" y="121" text-anchor="middle">Review</text>
<rect class="box" x="662" y="88" width="136" height="56" rx="8"/><text class="t" x="730" y="121" text-anchor="middle">Done</text>
<rect class="box hi" x="822" y="88" width="136" height="56" rx="8"/><text class="t" x="890" y="121" text-anchor="middle">Hand over</text>
<line class="edge" x1="158" y1="116" x2="180" y2="116" marker-end="url(#arrow-c)"/>
<line class="edge" x1="318" y1="116" x2="340" y2="116" marker-end="url(#arrow-c)"/>
<line class="edge" x1="478" y1="116" x2="500" y2="116" marker-end="url(#arrow-c)"/>
<line class="edge" x1="638" y1="116" x2="660" y2="116" marker-end="url(#arrow-c)"/>
<line class="edge" x1="798" y1="116" x2="820" y2="116" marker-end="url(#arrow-c)"/>
<text class="mono" x="90" y="172" text-anchor="middle">scan · graph · why</text>
<text class="mono" x="250" y="172" text-anchor="middle">impact &lt;path&gt;</text>
<text x="410" y="172" text-anchor="middle">after an edit <tspan class="mono">impact</tspan></text>
<text x="410" y="190" text-anchor="middle">on stop <tspan class="mono">check</tspan></text>
<text class="mono" x="570" y="172" text-anchor="middle">triage --since</text>
<text class="mono" x="730" y="172" text-anchor="middle">check --fail-on</text>
<text x="890" y="172" text-anchor="middle"><tspan class="mono">brief</tspan> → a PR comment</text>
<path class="edge" d="M890 144 L890 236 L90 236 L90 146" marker-end="url(#arrow-c)"/>
<text class="mut" x="490" y="258" text-anchor="middle">the next change, or the next person: the same picture, not a rebuilt context</text>
      """,
    ),
    "brief": Figure(
        viewbox="0 0 900 340",
        kind="",
        label="""The six parts of the brief: the scope line; Look first; What it did to the structure; Validation, split into candidate tests and the checks the host ran; Open for a person; Read this with care. Beside each, the principle it carries.""",
        body="""<rect class="box" x="20" y="14" width="430" height="312" rx="8"/>
<rect class="well" x="36" y="28" width="398" height="26" rx="4"/>
<text class="mono" x="46" y="46">base 922381d → HEAD 788f979 · 6 code files · 186 lines</text>
<rect class="well" x="36" y="64" width="398" height="70" rx="4"/>
<text class="t" x="46" y="82">Look first</text>
<text class="mut" x="46" y="100">#   File              Why                    This change  Owners       Flags</text>
<text class="mono" x="46" y="116">1   cli.py            15 commits in 90 days  +2 −2        T. Z. 100%   -</text>
<text class="mono" x="46" y="129">2   templates.py      12 commits in 90 days  +81 −3       T. Z. 100%   -</text>
<rect class="well" x="36" y="144" width="398" height="44" rx="4"/>
<text class="t" x="46" y="162">What it did to the structure</text>
<text class="mut" x="46" y="180">new orphans, cycles, imports of deleted files, unowned changes; what outside imports it</text>
<rect class="well" x="36" y="198" width="398" height="62" rx="4"/>
<text class="t" x="46" y="216">Validation</text>
<rect class="box" x="46" y="226" width="188" height="28" rx="4"/>
<text x="140" y="244" text-anchor="middle">candidate tests: paths, not results</text>
<rect class="box" x="246" y="226" width="188" height="28" rx="4"/>
<text x="340" y="244" text-anchor="middle">checks the host ran: its record</text>
<rect class="well" x="36" y="270" width="398" height="22" rx="4"/>
<text class="t" x="46" y="286">Open for a person</text>
<rect class="well" x="36" y="298" width="398" height="22" rx="4"/>
<text class="t" x="46" y="314">Read this with care</text>
<line class="soft" x1="434" y1="41" x2="484" y2="41"/>
<text x="490" y="38">First, which state the evidence describes:</text>
<text class="mut" x="490" y="54">the base, HEAD, and the uncommitted files in scope</text>
<line class="soft" x1="434" y1="99" x2="484" y2="99"/>
<text x="490" y="96">Ordered by two things: commits in 90 days, then lines</text>
<text class="mut" x="490" y="112">fix history, reach and owners are context, not multipliers</text>
<line class="soft" x1="434" y1="166" x2="484" y2="166"/>
<text x="490" y="163">Only the graph and reachability are compared</text>
<text class="mut" x="490" y="179">never status, confidence or owners between the two analyses</text>
<line class="soft" x1="434" y1="229" x2="484" y2="229"/>
<text x="490" y="226">Candidates apart from what ran</text>
<text class="mut" x="490" y="242">what ran comes from the host: --ran, --report, --coverage</text>
<line class="soft" x1="434" y1="281" x2="484" y2="281"/>
<text x="490" y="285">Where there is no evidence it says "needs a person", never "safe"</text>
<line class="soft" x1="434" y1="309" x2="484" y2="309"/>
<text x="490" y="313">What it cannot see, with the reason, instead of a blank</text>""",
    ),
}


def inline(name: str) -> str:
    """The figure for an HTML page whose stylesheet colours the classes."""
    f = FIGURES[name]
    return f'<svg viewBox="{f.viewbox}" role="img" aria-label="{html.escape(f.label, quote=True)}">\n{f.body}\n</svg>'


def standalone(name: str) -> str:
    """The figure as its own SVG document, styled for light and dark, on an opaque card."""
    f = FIGURES[name]
    width, height = f.viewbox.split()[2:]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{f.viewbox}" width="{width}" height="{height}" role="img" aria-labelledby="title">\n'
        f"<title id=\"title\">{html.escape(f.label)}</title>\n"
        f"<style>{_rules(LIGHT)}@media (prefers-color-scheme: dark){{{_rules(DARK)}}}</style>\n"
        f'<rect class="bg" width="{width}" height="{height}" rx="12"/>\n{f.body}\n</svg>\n'
    )


def write(directory: Path = OUT) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name in FIGURES:
        path = directory / f"{name}.svg"
        path.write_text(standalone(name), encoding="utf-8")
        written.append(path)
    return written


def stale(directory: Path = OUT) -> list[str]:
    """The figures whose file in `directory` is missing or differs from what this module makes."""
    return [name for name in FIGURES if not (directory / f"{name}.svg").is_file() or (directory / f"{name}.svg").read_text(encoding="utf-8") != standalone(name)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the guide's figures as SVG files, or check that they are current.")
    parser.add_argument("--out", type=Path, default=OUT, help=f"where the files go (default {OUT.relative_to(ROOT)})")
    parser.add_argument("--check", action="store_true", help="exit 1 and name the stale files instead of writing")
    args = parser.parse_args(argv)
    if args.check:
        old = stale(args.out)
        for name in old:
            print(f"stale: {args.out / (name + '.svg')}", file=sys.stderr)
        return 1 if old else 0
    for path in write(args.out):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
