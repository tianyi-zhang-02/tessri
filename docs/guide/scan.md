# What is unused: scan and reachability

`tessri scan` reads a repository once and gives every code file a status. Only reachability says a file is unused;
activity orders and qualifies the candidates.

Every code file gets one status:

| Status | Meaning |
|---|---|
| `ACTIVE` | touched in the last `active_days` (90), or not in git yet |
| `STABLE` | not touched recently, but other code depends on it. Normal. |
| `DORMANT` | untouched for `dormant_days` (365) and barely used |
| `ORPHAN` | no entry point, test or config reaches it: a cleanup candidate |

Only reachability says a file is unused. Activity orders and qualifies the candidates; it never
decides them. Files reached **only from tests** are listed separately: either production code
lost its caller, or it is test support.

```text
$ tessri why pkg/dead_dep.py
pkg/dead_dep.py  (Python, 1 code lines)
status:        ORPHAN (confidence high)
reachability:  NOT reachable from any entry point, test or config reference
depended on by: pkg/dead.py
named in config/scripts: none
mentioned in docs: none
depends on:    none
note:          only referenced by other unreachable files
```

A code file with definitions gets one more line, `definitions:`, holding each function, class and method against
the tests that reach the file: how many are named in one (the identifier appears in the test's code, strings and
comments apart: a mention, not an assertion), which are named in none, and which were not searched, being too
short, private by convention or too common (`default`, `constructor`, a dunder). The JSON has every definition with
its lines and the tests that name it; the [VS Code extension](vscode.md) shows the same on hover.

Each edge `why` lists carries the kind of evidence behind it, as `impact` names them, when that is anything but an
import statement: `pkg/loader.py (string)` depends on the file through a name in a string, `pkg/__init__.py [STABLE]
(package)` is the package file Python runs for an import, and a hop on the `reached via` route reads
`scripts/run.py -(string)-> pkg/loader.py`. An unmarked edge is an import.

The report's candidate table, most confident first:

| File | Code | Confidence | Last commit | Notes |
|---|---:|---|---|---|
| `pkg/dead_dep.py` | 1 | high | - | only referenced by other unreachable files |
| `pkg/dyn/z.py` | 1 | high | - | - |
| `pkg/dead.py` | 3 | medium | - | mentioned in docs: docs/guide.md |

Confidence drops one level per reason a file may still be wanted: modified recently, added
recently, not yet committed, mentioned in docs, lives under `scripts/`/`examples/`/`tools/`.

## How is reachability decided?

A file is reachable if an **entry point** leads to it through imports, or a **config reference** names it.
Tests are entry points of their own: code reached only from tests is reported as test-only.

**Python**

- Entry points: files with an `if __name__ == "__main__"` guard, `__main__.py`, `setup.py`/`conf.py`
  and similar, console-script entry points in `pyproject.toml`/`setup.cfg`, files named by
  CI/YAML/shell/Makefile (`pkg.mod.Class`, `scripts/run.py`), `entry` and `keep` from the config,
  and any Python file that cannot be parsed (so nothing it might import is blamed).
- Dynamic loading it understands: `import_module("pkg.mod")`, `"pkg.mod." + name`, and loops over
  a literal list of names (`for n in ("a", "b"): import_module(f".{n}", __name__)`).

**JavaScript / TypeScript** (the scanner reads `import`, `export ... from`, `require()`, `import()`,
`new URL("./x", import.meta.url)` and `/// <reference path>`; a `.vue`/`.svelte`/`.astro` file contributes its script blocks)

- Resolution follows the compiler: relative paths with extension probing (`./x.js` finds `x.ts`),
  directory `index` files, tsconfig `paths`/`baseUrl`/`extends` (JSONC is fine), `package.json`
  `imports`, workspace packages by name (`@acme/ui` and `@acme/ui/sub`, with a built `dist/index.js`
  mapped back to `src/index.ts`), and the `@/` and `~/` alias conventions.
- Entry points: `main`/`module`/`bin`/`exports` in any `package.json`, files named by `package.json`
  scripts, CI or HTML (`<script src="/src/main.tsx">`), shebang and `require.main === module` scripts,
  tool configs (`vite.config.ts`, `.eslintrc.js` ...), `.d.ts` files, Storybook stories, `.mdx` pages, and the
  file-based routes of a framework that is a dependency of the package: Next.js, Nuxt, Astro, SvelteKit,
  Remix / React Router, Gatsby, TanStack Router, Expo / React Native, Create React App, Vue CLI, Angular,
  NestJS, Docusaurus, VitePress, Vercel functions. The table is `_FRAMEWORKS` in `jsproject.py`.
- Dynamic loading it understands: ``import(`./pages/${name}.tsx`)``, `require("./x/" + name)`,
  `import.meta.glob("./routes/*.ts")`, `require.context(dir, recursive, /regex/)`.
- Tests: `*.test.*`, `*.spec.*`, `*.e2e.*`, `*.cy.*`, and `test/`, `tests/`, `__tests__/`, `e2e/`, `cypress/` directories.

Deliberately **not** evidence of use, for any language: tool configs that merely list files (`pyrefly.toml`,
`mypy.ini`, `.coveragerc`, lint sections), JSON data, docs, and anything under `docs/`/`reports/`.
Docs and data count as a *mention*, which lowers confidence but does not rescue a file.

A page (`.html`) is read in two parts. What it loads is wiring: a `src`, a `<link href>` and the code in its
inline `<script>` blocks, so `<script src="/src/main.tsx">` makes that file an entry point. What it says is a
mention: its text, a hyperlink (`<a href>`) and any other attribute. A landing page that names `pkg/core.py` in a
sentence documents the file, like a README does, and does not keep it alive. A page under `docs/` is all mention.

A file name found in a config, a script or a string names a file only when it fits exactly one. A bare `utils.py`
in a repository with ninety of them names none of them, and the report's caveats list such names with how many
files each fits; give the reference a directory (`pkg/utils.py`) or list the files under `entry`, which is taken to
mean every file it fits because you wrote it. The bare `__init__.py` and `__main__.py` never name a file.
