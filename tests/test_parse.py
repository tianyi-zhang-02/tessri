"""The Python analyzer reads a tree in one pass; it must find what a full `ast.walk` finds, and its cache entry must
give the same reading back."""

from __future__ import annotations

import ast
import unittest

from tessri.analyzers import python as P
from tessri.textrefs import DOTTED_FULL, PYPATH, is_filename

TRICKY = '''"""Module docstring: doc.module.Name and docs/module.py must not count."""
import os, sys as system
from . import sibling
from ..up import *
from pkg.sub import (a, b as c)


@decorate("deco.target.Name", path="tools/deco.py")
def f(x="arg.default.Name", *, y=lambda: "lam.bda.Name"):
    """Function docstring: doc.function.Name, docs/function.py."""
    s = "body.string.Name"
    t = f"pkg.dyn.{x}" + "tail.py"
    importlib.import_module(f"plugins.{x}")
    __import__("plug." + x)

    def inner():
        """Nested docstring: doc.inner.Name."""
        return "inner.body.Name"

    return "setup.py"


def g(): return "one.liner.Name"


async def h():
    """Async docstring: doc.async.Name."""
    await thing("async.body.Name")


@tag("cls.deco.Name")
class K(Base, metaclass="meta.kw.Name"):
    """Class docstring: doc.class.Name."""

    attr: "ann.otation.Name" = "cls.attr.Name"

    def m(self):
        if x == "if.test.Name":
            pass
        elif y == "elif.test.Name":
            for i in ["for.iter.Name", "for2.iter.Name"]:
                pass
            else:
                z = "for.else.Name"
        while w("while.test.Name"):
            break
        with open("with/item.py") as fh:
            pass
        try:
            pass
        except ValueError("exc.type.Name") as exc:
            q = "exc.body.Name"
        finally:
            q = "finally.body.Name"
        match p:
            case "match.value.Name":
                pass
            case {"k": v} if v == "guard.test.Name":
                r = "case.body.Name"


multi = """first line
pkg.multi.Name on an interior line, with scripts/interior.py
"""
ident = "justaname"
raw = b"by.tes.Name"
long = "x" * 3
if __name__ == "__main__":
    f()
'''


def reference(text: str) -> P._Info:
    """What the analyzer did before the one pass: every node, twice, with `ast.walk`."""
    tree = ast.parse(text)
    info = P._Info()
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
                info.doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            info.imports.extend(P._Import(a.name, (), 0) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            info.imports.append(P._Import(node.module or "", tuple(a.name for a in node.names if a.name != "*"), node.level))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            s = node.value
            if len(s) > 300:
                continue
            if DOTTED_FULL.fullmatch(s) and not is_filename(s):
                info.dotted.add(s)
            elif s.endswith(".") and DOTTED_FULL.fullmatch(s[:-1]):
                info.dotted.add(s[:-1])
            if ".py" in s:
                info.paths.update(PYPATH.findall(s))
            if len(s) <= 80 and P._IDENT.fullmatch(s):
                info.idents.add(s)
        elif isinstance(node, ast.Call) and node.args:
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            lead = P._leading_literal(node.args[0]) if name in ("import_module", "__import__") else None
            m = P._DYN_PREFIX.fullmatch(lead) if lead and lead.endswith(".") else None
            if m:
                info.dyn.append((len(m.group("dots")), m.group("rest")))
    info.main_guard = any(P._is_main_guard(n) for n in tree.body)
    return info


def fields(info: P._Info) -> dict:
    return {
        "imports": sorted((i.module, i.names, i.level) for i in info.imports),
        "dotted": info.dotted,
        "paths": info.paths,
        "idents": info.idents,
        "dyn": sorted(info.dyn),
        "main_guard": info.main_guard,
        "doc_lines": info.doc_lines,
    }


class OnePassTest(unittest.TestCase):
    def test_finds_what_the_full_walk_finds(self):
        found = P._parse("tricky.py", TRICKY)
        self.assertIsNotNone(found)
        self.assertEqual(fields(found), fields(reference(TRICKY)))

    def test_the_fixture_exercises_every_place(self):
        found = P._parse("tricky.py", TRICKY)
        # strings in a decorator, a default, a lambda, an annotation, a class keyword, a one-liner, a header, every
        # kind of body, a match pattern and a guard, and an interior line of a multi-line string
        for name in ("deco.target.Name", "arg.default.Name", "lam.bda.Name", "ann.otation.Name", "meta.kw.Name", "cls.deco.Name",
                     "one.liner.Name", "async.body.Name", "if.test.Name", "elif.test.Name", "for.iter.Name", "for.else.Name",
                     "while.test.Name", "exc.type.Name", "exc.body.Name", "finally.body.Name", "match.value.Name",
                     "guard.test.Name", "case.body.Name", "body.string.Name", "inner.body.Name", "cls.attr.Name"):
            self.assertIn(name, found.dotted, name)
        self.assertNotIn("pkg.multi.Name", found.dotted)  # a name inside a longer string is not a reference; a path is (below)
        self.assertIn("pkg.dyn", found.dotted)  # the literal head of an f-string, a name built at run time
        for doc in ("doc.module.Name", "doc.function.Name", "doc.inner.Name", "doc.async.Name", "doc.class.Name", "by.tes.Name"):
            self.assertNotIn(doc, found.dotted, doc)  # docstrings and bytes are not references
        self.assertEqual(found.paths, {"tools/deco.py", "tail.py", "setup.py", "with/item.py", "scripts/interior.py"})
        self.assertIn("justaname", found.idents)
        self.assertEqual(sorted(found.dyn), [(0, "plug"), (0, "plugins")])
        self.assertTrue(found.main_guard)
        self.assertEqual(sorted((i.module, i.level) for i in found.imports), [("", 1), ("os", 0), ("pkg.sub", 0), ("sys", 0), ("up", 2)])
        self.assertIn(1, found.doc_lines)
        self.assertIn(TRICKY.split("\n").index('    """Function docstring: doc.function.Name, docs/function.py."""') + 1, found.doc_lines)

    def test_a_file_that_does_not_parse(self):
        self.assertIsNone(P._parse("bad.py", "def (:\n"))

    def test_quote_counts(self):
        counts = P._quote_counts('a\nb = "x"\nc\nd = \'y\'\n')
        self.assertEqual(counts, [0, 0, 1, 1, 2, 2])  # one entry per line, plus the final empty line after the newline


class CacheEntryTest(unittest.TestCase):
    def test_round_trip(self):
        found = P._parse("tricky.py", TRICKY)
        back = P._from_cache(P._to_cache(found))
        self.assertEqual(fields(back), fields(found))
        self.assertEqual(back.modname, "")  # the names the tree gives a file are not kept; `run` sets them
        self.assertIsNone(P._from_cache(P._to_cache(None)))

    def test_doc_lines_as_ranges(self):
        self.assertEqual(P._ranges({1, 2, 3, 7, 9, 10}), [[1, 3], [7, 7], [9, 10]])
        self.assertEqual(P._ranges(set()), [])

    def test_a_malformed_entry_is_refused(self):
        for bad in (None, [], {"imports": "x"}, {"imports": [], "dotted": [], "paths": [], "idents": [], "dyn": [["a", 1]], "main_guard": False, "doc_lines": []}):
            with self.assertRaises(ValueError):
                P._from_cache(bad)


if __name__ == "__main__":
    unittest.main()
