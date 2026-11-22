# Review experience

## Task and scope

A maintainer takes over a change, identifies the files and relationships to read, checks the supplied validation,
and sees which questions still require a person. The site introduces that task with one generated teaching review;
the CLI renders the existing brief as an offline HTML file. No ranking, finding severity, policy or JSON field is
changed by the HTML view.

## One evidence object

`tessri brief --format html --out brief.html` calls the same `brief.compute` as Markdown and JSON.
`tessri/briefhtml.py` only renders that object. Its expandable sections retain file reasons and definitions,
owners, finding detail and action, every candidate test, supplied JUnit and coverage data, unsupported analysis,
open questions and the full JSON object. Files outside the initial attention limit remain in order under a counted
disclosure. No scripts or external assets are required, and the page stores no reviewed/accepted state.

Repository text is escaped before being placed in HTML, including titles, paths, commit subjects, host notes and
the full JSON. Only backtick spans become code elements; no repository-controlled URL becomes a link.

## A repeatable first review

`tools/review_example.py` creates a temporary repository with fixed commit dates and fixture identities.
A helper moves from `util/money.py` into billing; `reports/summary.py` remains unchanged and still imports it.
Two unittest cases exercise billing and really pass. An uncommitted annotation is then added so the scope visibly
includes working-tree contents. The resulting brief is published as HTML, Markdown and JSON under `example/`.
Its machine-local repository paths are replaced with a labelled placeholder before publication.

The site's hero draws the changed billing file, the deleted helper and the unchanged importer from this same
object, and the README's short excerpt is checked against the generated counts. The drawing distinguishes a retained
import from the removed import in the fixture's base. Its generator rejects evidence that no longer supports those
relationships or the recorded test result; it does not invent graph edges for arbitrary input. The worked example is labelled as teaching material, never as a production incident. The separate
`--demo` pages still analyze the actual checkout and identify branch/HEAD as a preview when appropriate.

The temporary fixture writes only to its own directory and cache, disables commit hooks and signing, and supplies
its own Git identities. It adds no runtime dependency to Tessri.

## Evidence and validation boundary

The view distinguishes candidate paths, host notes, JUnit outcomes and changed-line execution coverage. When any
validation is supplied, its association with the current code snapshot is explicitly unknown. Without supplied
results, the page says no check was recorded. Unsupported languages and skipped comparisons remain visible.

A future host contract could associate a run with captured source, tests, configuration and report contents.
That requires separate design and verification. File modification times or report timestamps alone are insufficient;
the renderer does not infer freshness. It also cannot establish assertion quality, runtime behavior or the absence
of defects.

## Editorial direction

The landing page leads with a full-width relationship diagram beneath a compact heading and introduction, then
task entry points, ranking evidence and engineering notes. Real-checkout output is available under a disclosure.
The home page uses sans-serif headings and a restrained accent; other pages retain their existing typography.
The shared palette, themes and footer look control remain available. On narrow screens the unchanged importer and
deleted module read first, with the billing change and tests below; the decorative SVG wires are replaced by an
explicit import label. Evidence links, search, focus styles and reduced-motion behavior remain accessible.
The README starts with the same worked review and one command. Detailed reference material stays in the guide.

Engineering posts explain a concrete problem, an initial hypothesis, evidence that changed a decision, the resulting
change and what remains uncertain. Teaching fixtures, historical claims with missing artifacts and single-machine
timings are labelled accordingly. The contribution guide records that standard.

## Validation

Automated checks cover round-tripping the full evidence object; escaping hostile repository text; expanding limited
attention; unknown/skipped analysis; supplied failures, unmatched results and unmeasured coverage; CLI HTML output;
and agreement between the generated review, landing page and README. The existing suite checks site links,
navigation, search, themes and source rendering.

Visual checks cover the landing page, a guide page, a post and the offline brief at desktop and narrow widths,
with dark/light reading and keyboard-operated disclosures. These checks establish behavior and presentation,
not reviewer benefit.

A small future task trial should compare ordinary review materials with the same workflow plus a brief, using
different but comparable Python and JS/TS tasks with ordering exchanged. Record context-gathering time, missed
important findings, irrelevant jumps, setup effort and interruptions. A few maintainers can expose usability
problems; they do not establish a general speedup.
