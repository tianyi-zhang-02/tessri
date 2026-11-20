import unittest

from helpers import TempRepo, write_tree
from tessri import config
from tessri.analyze import analyze
from tessri.analyzers.jslex import scan
from tessri.explain import explain

APP = {
    "package.json": '{"name": "app", "main": "dist/server.js", "bin": {"app": "./dist/cli.js"}, "scripts": {"gen": "node scripts/gen.mjs"}}',
    "tsconfig.json": '{\n  // JSONC: comments and trailing commas are legal here\n  "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"],},},\n}\n',
    "index.html": '<script type="module" src="/src/main.tsx"></script>\n',
    "src/main.tsx": (
        'import App from "@/App";\n'
        'import "./styles.css";\n'
        'import "./router";\n'
        'import "./plugins";\n'
        'import "./fake";\n'
        'const Lazy = lazy(() => import("./pages/Lazy"));\n'
        'const worker = new URL("./worker.ts", import.meta.url);\n'
    ),
    "src/App.tsx": (
        'import { util } from "./lib/util.js";\n'
        'import type { T } from "./types";\n'
        'import Widget from "./Widget.vue";\n'
        "export default function App() { return <p>Don't panic</p>; }\n"
    ),
    "src/lib/util.ts": "export const util = 1;\n",
    "src/types.ts": "export type T = string;\n",
    "src/pages/Lazy.tsx": "export default () => null;\n",
    "src/router.ts": "export const routes = import.meta.glob('./routes/*.ts');\n",
    "src/routes/a.ts": "export default 1;\n",
    "src/routes/b.ts": "export default 2;\n",
    "src/plugins/index.ts": "export const load = (n: string) => import(`./${n}.plugin.ts`);\n",
    "src/plugins/x.plugin.ts": "export default 1;\n",
    "src/plugins/skip.ts": "export default 0;\n",  # does not fit the template's .plugin.ts tail
    "src/worker.ts": "self.onmessage = () => {};\n",
    "src/Widget.vue": '<template><p /></template>\n<script setup lang="ts">\nimport { shared } from "./lib/shared";\n</script>\n',
    "src/lib/shared.ts": "export const shared = 1;\n",
    "src/Unused.svelte": "<script>\n  let a = 1;\n</script>\n",
    "src/fake.ts": "// import dead from './dead'\nexport const s = \"import dead from './dead'\";\n",
    "src/dead.ts": "import { y } from './dead_dep';\nexport const x = y;\n",
    "src/dead_dep.ts": "export const y = 1;\n",
    "src/server.ts": "export {};\n",
    "src/cli.ts": "export {};\n",
    "src/types/env.d.ts": "declare const __DEV__: boolean;\n",
    "src/chart.ts": "export const chart = 1;\n",
    "docs/intro.mdx": "import { chart } from '../src/chart'\n\n# Intro\n",
    "src/App.test.tsx": 'import App from "./App";\nimport { helper } from "./test-only";\ntest("x", () => App && helper);\n',
    "src/test-only.ts": "export const helper = 1;\n",
    "vite.config.ts": 'import { plugin } from "./tools/helper";\nexport default { plugins: [plugin] };\n',
    "tools/helper.ts": "export const plugin = 1;\n",
    "scripts/gen.mjs": "console.log('gen');\n",
    "scripts/old.mjs": "console.log('old');\n",
    "bin/legacy.js": "#!/usr/bin/env node\nconst dep = require('./legacy-dep');\n",
    "bin/legacy-dep.js": "module.exports = 1;\n",
}

MONOREPO = {
    "package.json": '{"name": "root", "private": true, "workspaces": ["apps/*", "packages/*"]}',
    "apps/web/package.json": '{"name": "web", "dependencies": {"next": "15", "@acme/ui": "*"}}',
    "apps/web/app/page.tsx": 'import { Button } from "@acme/ui";\nimport { help } from "@acme/ui/helpers";\nimport { Card } from "../components/Card";\n',
    "apps/web/app/layout.tsx": "export default function Layout() { return null; }\n",
    "apps/web/app/api/hello/route.ts": "export const GET = () => new Response('hi');\n",
    "apps/web/middleware.ts": "export {};\n",
    "apps/web/components/Card.tsx": "export const Card = 1;\n",
    "apps/web/components/Unused.tsx": "export const Unused = 1;\n",
    "packages/ui/package.json": '{"name": "@acme/ui", "main": "dist/index.js", "types": "dist/index.d.ts"}',
    "packages/ui/src/index.ts": "export * from './button';\n",
    "packages/ui/src/button.ts": "export const Button = 1;\n",
    "packages/ui/src/helpers.ts": "export const help = 1;\n",
    "packages/ui/src/orphan.ts": "export const orphan = 1;\n",
    "packages/ui/pages/extra.ts": "export const extra = 1;\n",  # not a Next.js package, so pages/ means nothing here
}


def statuses(a, status):
    return {p for p, r in a.records.items() if r.status == status}


class LexerTest(unittest.TestCase):
    def test_comments_strings_and_regexes_are_not_imports(self):
        found = scan(
            "// import a from './comment'\n"
            "/* import b from './block' */\n"
            "const s = \"import c from './string'\";\n"
            "const r = /'/g; const t = `import d from './tpl'`;\n"
            "import('./after');\n"
        )
        self.assertEqual(found.specs, ["./after"])

    def test_forms_of_import(self):
        found = scan(
            "import React, { useState } from 'react'\n"
            "import type { A } from './a'\n"
            "import * as ns from './ns'\n"
            "import './side'\n"
            "export * from './re'\n"
            "export { x } from './named'\n"
            "import eq = require('./eq')\n"
            "const c = require('./cjs'), r = require.resolve('./resolved')\n"
            "const { x } = await import(`./static-template`)\n"
        )
        self.assertEqual(found.specs, ["react", "./a", "./ns", "./side", "./re", "./named", "./eq", "./cjs", "./resolved", "./static-template"])

    def test_computed_specifiers_keep_their_literal_parts(self):
        found = scan("import(`./pages/${name}.tsx`); require('./lazy/' + n + '.js'); require.context('./icons', false, /\\.svg$/)")
        self.assertEqual([(d.head, d.tail) for d in found.dynamic], [("./pages/", ".tsx"), ("./lazy/", ".js")])
        self.assertEqual(found.contexts, [("./icons", False, "/\\.svg$/")])

    def test_shapes_found_in_real_packages(self):
        # Each of these once broke the scanner on third-party code (found by diffing against the TypeScript compiler).
        found = scan(
            "module.exports = { ...require('./spread') };\n"
            "const m = require('./member'); obj.require('./not-an-import');\n"
            "const s = `^(?!${paths.map((p) => p.replace(/\\//g, '-')).join('|')})`;\n"  # an escaped slash in a regex inside ${}
            "await import(\n  /* @vite-ignore */\n  './commented'\n);\n"
        )
        self.assertEqual(found.specs, ["./spread", "./member", "./commented"])

    def test_unreadable_source_is_reported_not_guessed(self):
        self.assertIsNone(scan("const a = `never closed"))
        self.assertIsNone(scan("/* never closed"))


class AppReachabilityTest(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, APP)
        self.a = analyze(self.root, config.load(self.root))

    def reach(self, path):
        return self.a.records[path].reachability

    def test_orphans_are_only_the_unreferenced_files(self):
        orphans = {p for p, r in self.a.records.items() if r.status == "ORPHAN"}
        self.assertEqual(orphans, {"src/dead.ts", "src/dead_dep.ts", "src/Unused.svelte", "src/plugins/skip.ts", "scripts/old.mjs"})

    def test_commented_and_quoted_imports_do_not_rescue_a_file(self):
        self.assertEqual(self.reach("src/dead.ts"), "none")

    def test_tsconfig_alias_and_js_spelling_of_a_ts_source(self):
        self.assertEqual(self.reach("src/App.tsx"), "prod")  # only imported as "@/App", from tsconfig paths in JSONC
        self.assertEqual(self.reach("src/lib/util.ts"), "prod")  # imported as "./lib/util.js"

    def test_dynamic_loading_forms(self):
        for path in ("src/pages/Lazy.tsx", "src/routes/a.ts", "src/routes/b.ts", "src/plugins/x.plugin.ts", "src/worker.ts"):
            self.assertEqual(self.reach(path), "prod", path)

    def test_code_imported_only_from_components_and_mdx(self):
        self.assertEqual(self.reach("src/lib/shared.ts"), "prod")  # imported from a <script setup> in a .vue file
        self.assertEqual(self.reach("src/chart.ts"), "prod")  # imported from an .mdx page
        self.assertEqual(self.a.records["src/Widget.vue"].language, "Vue")

    def test_entry_points(self):
        roots = {p: r.roots for p, r in self.a.records.items() if r.roots}
        self.assertEqual(roots["src/main.tsx"], ["config-ref: index.html"])
        self.assertEqual(roots["src/server.ts"], ["package.json: main"])  # dist/server.js is built from src/server.ts
        self.assertEqual(roots["src/cli.ts"], ["package.json: bin"])
        self.assertEqual(roots["scripts/gen.mjs"], ["config-ref: package.json"])
        self.assertEqual(roots["vite.config.ts"], ["tool-config"])
        self.assertEqual(roots["bin/legacy.js"], ["shebang"])
        self.assertEqual(roots["src/types/env.d.ts"], ["declaration-file"])
        self.assertEqual(self.reach("tools/helper.ts"), "prod")  # imported by the tool config
        self.assertEqual(self.reach("bin/legacy-dep.js"), "prod")

    def test_test_only_code(self):
        self.assertEqual(self.reach("src/test-only.ts"), "test")
        self.assertTrue(self.a.records["src/App.test.tsx"].is_test)
        self.assertNotIn(self.a.records["src/test-only.ts"].status, ("ORPHAN",))

    def test_unterminated_template_is_an_entry_point_not_a_verdict(self):
        write_tree(self.root, {"src/broken.ts": "const a = `oops\nimport './dead';\n"})
        a = analyze(self.root, config.load(self.root))
        self.assertIn("src/broken.ts", a.unparsed)
        self.assertEqual(a.records["src/broken.ts"].reachability, "prod")

    def test_why_explains_a_js_verdict(self):
        text = explain(self.a, "src/lib/shared.ts")
        self.assertIn("src/Widget.vue -> src/lib/shared.ts", text)


class MonorepoTest(TempRepo):
    def setUp(self):
        super().setUp()
        write_tree(self.root, MONOREPO)
        self.a = analyze(self.root, config.load(self.root))

    def test_workspace_packages_and_frameworks(self):
        rec = self.a.records
        self.assertEqual(rec["packages/ui/src/button.ts"].reachability, "prod")  # via "@acme/ui" -> dist/index.js -> src/index.ts
        self.assertEqual(rec["packages/ui/src/helpers.ts"].reachability, "prod")  # via "@acme/ui/helpers"
        self.assertEqual(rec["apps/web/components/Card.tsx"].reachability, "prod")

    def test_framework_conventions_only_apply_where_the_framework_is_a_dependency(self):
        rec = self.a.records
        self.assertEqual(rec["apps/web/app/page.tsx"].roots, ["Next.js convention"])
        for path in ("apps/web/app/layout.tsx", "apps/web/app/api/hello/route.ts", "apps/web/middleware.ts"):
            self.assertEqual(rec[path].reachability, "prod", path)
        self.assertEqual(statuses(self.a, "ORPHAN"), {"apps/web/components/Unused.tsx", "packages/ui/src/orphan.ts", "packages/ui/pages/extra.ts"})


RESOLUTION = {
    "package.json": (
        '{"name": "x", "dependencies": {"astro": "5"}, "imports": {"#internal/*": "./src/internal/*.js"},'
        ' "exports": {".": "./dist/main.js", "./util": {"import": "./dist/util.js"}}}'
    ),
    "config/tsconfig.base.json": '{"compilerOptions": {"baseUrl": "../src", "paths": {"~lib/*": ["lib/*"]}}}',
    "tsconfig.json": '{"extends": "./config/tsconfig.base.json"}',
    "src/main.ts": (
        'import a from "~lib/a";\n'  # paths inherited through `extends` from another directory; relative to the file that defines baseUrl
        'import b from "#internal/b";\n'  # package.json "imports"
        'import c from "components/c";\n'  # bare name through baseUrl
        'const ctx = require.context("./ctx", false, /\\.ts$/);\n'
    ),
    "src/lib/a.ts": "export default 1;\n",
    "src/internal/b.ts": "export default 2;\n",
    "src/components/c.ts": "export default 3;\n",
    "src/ctx/one.ts": "export default 4;\n",
    "src/ctx/sub/two.ts": "export default 5;\n",  # require.context(..., false) does not recurse
    "src/util.ts": "export {};\n",  # exports["./util"] -> dist/util.js
    "src/pages/Page.astro": '---\nimport { f } from "../lib/front";\n---\n<h1>hi</h1>\n<script src="./legacy.ts"></script>\n',
    "src/lib/front.ts": "export const f = 1;\n",
    "src/pages/legacy.ts": "export {};\n",
}


class ResolutionTest(TempRepo):
    def test_aliases_exports_and_contexts(self):
        write_tree(self.root, RESOLUTION)
        a = analyze(self.root, config.load(self.root))
        self.assertEqual(statuses(a, "ORPHAN"), {"src/ctx/sub/two.ts"})
        self.assertEqual(a.records["src/main.ts"].roots, ["package.json: exports ."])  # dist/main.js is built from src/main.ts
        self.assertEqual(a.records["src/util.ts"].roots, ["package.json: exports ./util"])
        self.assertEqual(a.records["src/pages/Page.astro"].roots, ["Astro convention"])

    def test_an_astro_file_with_crlf_line_endings_keeps_its_frontmatter_imports(self):
        write_tree(self.root, {
            "package.json": '{"dependencies": {"astro": "5"}}',
            "src/pages/Page.astro": '---\r\nimport { f } from "../lib/front";\r\n---\r\n<h1>hi</h1>\r\n',
            "src/lib/front.ts": "export const f = 1;\r\n",
        })
        a = analyze(self.root, config.load(self.root))
        self.assertEqual(statuses(a, "ORPHAN"), set())  # front.ts is reached through the frontmatter

    def test_other_framework_conventions(self):
        cases = [
            ("@sveltejs/kit", "src/routes/+page.ts", "SvelteKit"),
            ("nuxt", "composables/useThing.ts", "Nuxt"),
            ("gatsby", "gatsby-node.js", "Gatsby"),
            ("react-scripts", "src/index.js", "Create React App"),
            ("@remix-run/react", "app/routes/_index.tsx", "Remix / React Router"),
        ]
        for dep, path, label in cases:
            with self.subTest(dep=dep):
                root = self.root / dep.replace("/", "_")
                write_tree(root, {"package.json": '{"dependencies": {"%s": "1"}}' % dep, path: "export {};\n"})
                self.assertEqual(analyze(root, config.load(root)).records[path].roots, [f"{label} convention"])
        bare = self.root / "no-framework"
        write_tree(bare, {"package.json": "{}", "src/routes/+page.ts": "export {};\n"})
        self.assertEqual(analyze(bare, config.load(bare)).records["src/routes/+page.ts"].status, "ORPHAN")


if __name__ == "__main__":
    unittest.main()
