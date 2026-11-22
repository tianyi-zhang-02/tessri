"""The function, class and type definitions of a JavaScript or TypeScript source, with their line spans, without a parser.

`symbols` names what a change touched by the innermost definition that holds each changed line. Python has `ast`
for that; JavaScript has no parser in the standard library, so this reads the lexical layer the way `jslex` does
for imports: tokens, with strings, templates, comments and regex literals told apart from code, then braces matched
to find each body. A definition is a function declaration, a class and its methods, a `const`/`let`/`var` or a member
(`Foo.prototype.bar`, `exports.run`, `this.handle` in a class) assigned a function, an arrow function, a class or an
object literal, the methods and function-valued keys of such an object (`nodeOps.insert`), and in TypeScript an
interface, a type alias, an enum or a namespace. A definition inside another is named through it (`Shape.area`,
`outer.inner`); a callback or an object literal passed as an argument has no name of its own, so what it holds is
named by the definition around it, except a test's callback (`describe`, `it`, `test`), which its title names. A source whose braces do not balance, or whose string, template or comment never
closes, is not read: a span from it would be a guess. JSX makes the lexical layer ambiguous (an apostrophe or a
slash in text between elements), and the two cases met so far are told apart by what precedes them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import jslex

LOOKAHEAD = 400  # tokens a head may span (parameters, types, decorators) before it is given up

_TOKEN = re.compile(
    r"""(?P<ws>\s+)|(?P<line>//[^\n]*)|(?P<block>/\*.*?\*/)"""
    r"""|(?P<str>'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")|(?P<tpl>`)"""
    r"""|(?P<num>\d(?:[\w.]|[eE][+-])*)|(?P<word>[A-Za-z_$#][\w$]*)"""
    r"""|(?P<op>=>|\?\.|\.\.\.|[{}()\[\];,.:=<>?!&|+\-*/%^~@])|(?P<other>.)""",
    re.S,
)
_MODIFIERS = frozenset(("static", "async", "public", "private", "protected", "readonly", "override", "abstract", "declare", "accessor", "get", "set"))
_CONTINUES_AFTER = frozenset((".", "?.", "?", ":", "&", "|", "=", "+", "-", "*", "/", "%", "^", "~", "=>", ",", "(", "["))  # not `>`: a JSX tag ends a line
_CONTINUES_BEFORE = frozenset((".", "?.", "?", ":", "&", "|", "=", "+", "-", "*", "/", "%", "<", ">", "^", "=>", ",", "(", "["))
_CONTINUES_WORDS = frozenset(("in", "instanceof", "as", "satisfies", "extends", "keyof", "typeof", "infer", "is", "asserts"))
_OPEN = {"(": ")", "[": "]", "{": "}", "<": ">"}
_TEST_WORDS = frozenset(("describe", "it", "test", "suite", "bench", "context", "specify"))  # a titled callback is named by its title
_TEST_MODIFIERS = frozenset(("only", "skip", "concurrent", "sequential", "todo", "fails", "runIf", "skipIf"))
TITLE = 40  # characters of a test title kept in its name


@dataclass(slots=True)
class Token:
    kind: str  # word, str, tpl, num, re, op
    text: str
    line: int  # first line, 1-based
    end: int  # last line: a template literal spans several


@dataclass(slots=True)
class _Frame:
    kind: str  # block (no name of its own), function, class, namespace, interface, enum
    prefix: str  # what a definition opened inside is named through
    index: int | None  # the definition this brace closes, if any


def _regex_at(text: str, i: int) -> bool:
    """Whether the `/` at `i` opens a regex literal: judged by the previous token as in `jslex`, except in what JSX
    makes likely: `</` closes a tag, `/>` ends one, and a slash after `}` or `>` is text between elements."""
    if text[i + 1 : i + 2] == ">" or (i > 0 and text[i - 1] == "<"):
        return False
    j = i - 1
    while j >= 0 and text[j] in " \t\r\n":
        j -= 1
    if j >= 0 and (text[j] == "}" or (text[j] == ">" and text[j - 1 : j] != "=")):  # after `=>` a regex is fine
        return False
    return jslex._regex_allowed(text, i)


def _apostrophe(text: str, i: int) -> bool:
    """Whether the quote at `i` is an apostrophe in JSX text (`Don't`) rather than a string's opening: no string
    opens right after a word character in JavaScript."""
    return i > 0 and (text[i - 1].isalnum() or text[i - 1] in "_$")


def tokens(text: str) -> list[Token] | None:
    """The significant tokens of `text` in order, or None when a template literal or block comment never closes."""
    out: list[Token] = []
    newline = text.find("\n")
    i = (len(text) if newline < 0 else newline + 1) if text.startswith("#!") else 0
    line = 1 if i == 0 else 2
    n = len(text)
    while i < n:
        m = _TOKEN.match(text, i)
        if m is None:  # cannot happen: `other` takes any character
            return None
        kind, chunk = m.lastgroup, m.group()
        if kind == "tpl":
            parsed = jslex._template(text, i)
            if parsed is None:
                return None
            end = parsed[0]
            chunk = text[i:end]
            out.append(Token("tpl", chunk, line, line + chunk.count("\n")))
        elif kind == "op" and chunk == "/":
            if text.startswith("/*", i):
                return None  # a closed block comment would have matched above
            regex = jslex._REGEX.match(text, i) if _regex_at(text, i) else None
            if regex:
                chunk = regex.group()
                out.append(Token("re", chunk, line, line))
            else:
                out.append(Token("op", chunk, line, line))
        elif kind == "str" and _apostrophe(text, i):
            chunk = chunk[0]  # skip the quote alone; the text after it is read as code, which cannot open braces
        elif kind in ("word", "str", "num", "op"):
            out.append(Token(kind, chunk, line, line))
        line += chunk.count("\n")
        i += len(chunk)
    return out


def _is(t: Token | None, kind: str, text: str | None = None) -> bool:
    return t is not None and t.kind == kind and (text is None or t.text == text)


def _at(toks: list[Token], i: int) -> Token | None:
    return toks[i] if 0 <= i < len(toks) else None


def _match(toks: list[Token], i: int, angles: bool = False) -> int | None:
    """Index of the bracket closing the one at `i`, counting `(`, `[`, `{` (and `<` when `angles`) alike, or None
    when none closes it within reach."""
    stack: list[str] = []
    for j in range(i, min(len(toks), i + LOOKAHEAD * 4)):
        t = toks[j]
        if t.kind != "op":
            continue
        if t.text in _OPEN and (angles or t.text != "<"):
            stack.append(_OPEN[t.text])
        elif t.text in (")", "]", "}") or (angles and t.text == ">"):
            if not stack or stack[-1] != t.text:
                return None
            stack.pop()
            if not stack:
                return j
    return None


def _breaks(toks: list[Token], j: int) -> bool:
    """Whether a statement without a `;` ends between `toks[j]` and the next token: a line break that neither side
    continues across with an operator, a type or expression keyword, a template or an opening brace."""
    t, after = toks[j], _at(toks, j + 1)
    if after is None or after.line <= t.end:
        return False
    if (t.kind == "op" and t.text in _CONTINUES_AFTER) or (t.kind == "word" and t.text in _CONTINUES_WORDS):
        return False
    if (after.kind == "op" and (after.text in _CONTINUES_BEFORE or after.text == "{")) or (after.kind == "word" and after.text in _CONTINUES_WORDS):
        return False
    return after.kind != "tpl"


def _skip_type(toks: list[Token], i: int, until: tuple[str, ...]) -> int | None:
    """From the token after a `:`, the index of the first token in `until` at bracket depth 0, or None when a `;`,
    a `,`, a closing bracket or a new statement comes first: the annotation ran to the end of its own."""
    depth = 0
    for j in range(i, min(len(toks), i + LOOKAHEAD)):
        t = toks[j]
        if t.kind == "op":
            if depth == 0 and t.text in until:
                return j
            if t.text in "([{<":
                depth += 1
            elif t.text in ")]}>":
                if depth == 0:
                    return None
                depth -= 1
            elif depth == 0 and t.text in (";", ","):
                return None
        if depth == 0 and _breaks(toks, j):
            return None
    return None


def _body(toks: list[Token], i: int) -> int | None:
    """The `{` opening the body of a function whose parameters closed just before `i`: at `i`, or after a return type
    (`: Promise<T>`, `: { a: number }`); None when a `;` comes first, as in an overload or an abstract method."""
    if _is(toks[i] if i < len(toks) else None, "op", "{"):
        return i
    if not _is(_at(toks, i), "op", ":"):
        return None
    depth = 0
    for j in range(i + 1, min(len(toks), i + LOOKAHEAD)):
        t = toks[j]
        if t.kind == "op":
            if t.text == "{" and depth == 0:
                before = toks[j - 1]
                if not ((before.kind == "op" and before.text in (":", "|", "&", "=>", "?")) or _is(before, "word", "extends")):
                    return j  # the body: an object type opens after `:`, `|`, `&`, `=>`, `?` or `extends`, never after a type's last token
                depth += 1
            elif t.text in "([<{":
                depth += 1
            elif t.text in ")]>}":
                if depth == 0:
                    return None
                depth -= 1
            elif depth == 0 and t.text in (";", ","):
                return None
        if depth == 0 and _breaks(toks, j):
            return None  # an overload or an abstract method without a `;`
    return None


def _head_body(toks: list[Token], i: int) -> int | None:
    """The `{` opening a class, interface or namespace body whose name ended just before `i`: past `extends`,
    `implements` and generics."""
    depth = 0
    for j in range(i, min(len(toks), i + LOOKAHEAD)):
        t = toks[j]
        if t.kind != "op":
            continue
        if t.text == "{" and depth == 0:
            return j
        if t.text in "([<{":
            depth += 1
        elif t.text in ")]>}":
            if depth == 0:
                return None
            depth -= 1
        elif depth == 0 and t.text == ";":
            return None
    return None


def _value(toks: list[Token], i: int) -> tuple[str, int, bool] | None:
    """What is assigned at `i` when it is a function, an arrow function or a class: (kind, index of the body's `{`
    or of the arrow's expression, whether that is a block); None for any other value."""
    j = i
    if _is(_at(toks, j), "word", "async") and not _is(_at(toks, j + 1), "op", "=>"):
        j += 1
    t = _at(toks, j)
    if _is(t, "word", "function"):
        j += 1
        if _is(_at(toks, j), "op", "*"):
            j += 1
        if _is(_at(toks, j), "word"):
            j += 1
        if _is(_at(toks, j), "op", "<"):
            close = _match(toks, j, angles=True)
            if close is None:
                return None
            j = close + 1
        if not _is(_at(toks, j), "op", "("):
            return None
        close = _match(toks, j)
        if close is None:
            return None
        body = _body(toks, close + 1)
        return None if body is None else ("function", body, True)
    if _is(t, "word", "class"):
        body = _head_body(toks, j + 1)
        return None if body is None else ("class", body, True)
    if _is(t, "op", "{"):
        return ("object", j, True)
    if _is(t, "op", "<"):  # a generic arrow: `<T,>(x: T) => x`
        close = _match(toks, j, angles=True)
        if close is None:
            return None
        j = close + 1
        t = _at(toks, j)
    if _is(t, "op", "("):
        close = _match(toks, j)
        if close is None:
            return None
        k = close + 1
        if _is(_at(toks, k), "op", ":"):
            k = _skip_type(toks, k + 1, ("=>",))
            if k is None:
                return None
    elif _is(t, "word"):
        k = j + 1
    else:
        return None
    if not _is(_at(toks, k), "op", "=>"):
        return None
    body = k + 1
    if body >= len(toks):
        return None
    return ("function", body, _is(toks[body], "op", "{"))


def _expression_end(toks: list[Token], i: int) -> int:
    """Index of the last token of the expression starting at `i`: before a `;`, a `,` or a closing bracket at depth
    0, or at a line break that nothing continues across."""
    depth = 0
    j = i
    while j < len(toks):
        t = toks[j]
        if t.kind == "op":
            if t.text in "([{":
                depth += 1
            elif t.text in ")]}":
                if depth == 0:
                    return max(i, j - 1)
                depth -= 1
            elif depth == 0 and t.text in (";", ","):
                return max(i, j - 1)
        if j + 1 >= len(toks) or (depth == 0 and _breaks(toks, j)):
            return j
        j += 1
    return len(toks) - 1


def _skip_decorators(toks: list[Token], j: int) -> int | None:
    while _is(_at(toks, j), "op", "@"):
        j += 1
        if not _is(_at(toks, j), "word"):
            return None
        j += 1
        while _is(_at(toks, j), "op", ".") and _is(_at(toks, j + 1), "word"):
            j += 2
        if _is(_at(toks, j), "op", "("):
            close = _match(toks, j)
            if close is None:
                return None
            j = close + 1
    return j


def _member_name(parts: list[str], stack: list[_Frame]) -> tuple[str, str] | None:
    """The name a member assignment defines and the prefix it goes under: `exports.run` and `module.exports.run`
    are `run`, `Foo.prototype.bar` is `Foo.bar`, `this.handle` is named under the enclosing class."""
    prefix = stack[-1].prefix if stack else ""
    if parts[0] == "this":
        parts = parts[1:]
        prefix = next((f.prefix for f in reversed(stack) if f.kind == "class"), prefix)
    elif parts[:2] == ["module", "exports"]:
        parts = parts[2:] or ["module.exports"]
    elif parts[0] == "exports":
        parts = parts[1:]
    parts = [p for p in parts if p != "prototype"]
    return (".".join(parts), prefix) if parts else None


def _titled(toks: list[Token], i: int, stack: list[_Frame]) -> tuple[str, str, str, int, bool] | None:
    """`describe("ref", () => {`, `it.only('unwraps', async function () {`: the callback, named by its title, so a
    change inside a test is named by the test rather than left at module level."""
    k = i + 1
    while _is(_at(toks, k), "op", ".") and _is(_at(toks, k + 1), "word") and toks[k + 1].text in _TEST_MODIFIERS:
        k += 2
    title = _at(toks, k + 1)
    if not (_is(_at(toks, k), "op", "(") and title is not None and title.kind in ("str", "tpl") and _is(_at(toks, k + 2), "op", ",")):
        return None
    name = " ".join(title.text[1:-1].split())
    if not name or "${" in name:
        return None
    value = _value(toks, k + 3)
    if value is None or value[0] != "function":
        return None
    prefix = stack[-1].prefix if stack else ""
    return (name if len(name) <= TITLE else name[: TITLE - 1] + "…", prefix, "function", value[1], value[2])


def _member(toks: list[Token], i: int, stack: list[_Frame]) -> tuple[str, str, str, int, bool] | None:
    """`a.b.c = <function, class or exported object>` at `i`: (name, prefix, kind, body index, block). Outside a class
    only a module's own statements count (`Foo.prototype.bar`, `exports.run`, also inside a wrapping IIFE): a property
    set inside a named function is a step of that function, not a definition."""
    parts = [toks[i].text]
    if parts[0] != "this" and stack and stack[-1].prefix:
        return None
    j = i + 1
    while _is(_at(toks, j), "op", ".") and _is(_at(toks, j + 1), "word"):
        parts.append(toks[j + 1].text)
        j += 2
    if len(parts) < 2 or not _is(_at(toks, j), "op", "=") or _is(_at(toks, j + 1), "op", "="):
        return None
    value = _value(toks, j + 1)
    named = _member_name(parts, stack)
    if value is None or named is None:
        return None
    if value[0] == "object" and not (parts[0] == "exports" or parts[:2] == ["module", "exports"]):
        return None  # `sref.value = { a: 2 }` is a statement; `module.exports = { ... }` names a module's definitions
    return (named[0], named[1], value[0], value[1], value[2])


def _statement(toks: list[Token], i: int, stack: list[_Frame]) -> tuple[str, str, str, int, bool] | None:
    """A definition starting at `i` in a module, namespace or function body: (name, prefix, frame kind, index of the
    body's `{` or the arrow's expression, whether that is a block); None when the statement defines nothing."""
    prefix = stack[-1].prefix if stack else ""
    j = _skip_decorators(toks, i)
    if j is None:
        return None
    default = False
    while True:
        t = _at(toks, j)
        if _is(t, "op", "@"):
            j = _skip_decorators(toks, j)
            if j is None:
                return None
        elif _is(t, "word") and t.text in ("export", "declare", "abstract"):
            j += 1
        elif _is(t, "word", "default") and j > i and _is(toks[j - 1], "word", "export"):
            default = True
            j += 1
        else:
            break
    t = _at(toks, j)
    if t is None:
        return None
    if _is(t, "word", "async") and _is(_at(toks, j + 1), "word", "function"):
        j += 1
        t = toks[j]
    if _is(t, "word", "function"):
        j += 1
        if _is(_at(toks, j), "op", "*"):
            j += 1
        if _is(_at(toks, j), "word"):
            name = toks[j].text
            j += 1
        elif default:
            name = "default"
        else:
            return None
        if _is(_at(toks, j), "op", "<"):
            close = _match(toks, j, angles=True)
            if close is None:
                return None
            j = close + 1
        if not _is(_at(toks, j), "op", "("):
            return None
        close = _match(toks, j)
        if close is None:
            return None
        body = _body(toks, close + 1)
        return None if body is None else (name, prefix, "function", body, True)
    if _is(t, "word", "class"):
        if _is(_at(toks, j + 1), "word") and toks[j + 1].text not in ("extends", "implements"):
            name = toks[j + 1].text
            j += 2
        elif default:
            name = "default"
            j += 1
        else:
            return None
        body = _head_body(toks, j)
        return None if body is None else (name, prefix, "class", body, True)
    if _is(t, "word", "interface") and _is(_at(toks, j + 1), "word"):
        body = _head_body(toks, j + 2)
        return None if body is None else (toks[j + 1].text, prefix, "interface", body, True)
    if _is(t, "word", "const") and _is(_at(toks, j + 1), "word", "enum"):
        j += 1
        t = toks[j]
    if _is(t, "word", "enum") and _is(_at(toks, j + 1), "word") and _is(_at(toks, j + 2), "op", "{"):
        return (toks[j + 1].text, prefix, "enum", j + 2, True)
    if _is(t, "word") and t.text in ("namespace", "module") and _is(_at(toks, j + 1), "word"):
        parts = [toks[j + 1].text]
        j += 2
        while _is(_at(toks, j), "op", ".") and _is(_at(toks, j + 1), "word"):
            parts.append(toks[j + 1].text)
            j += 2
        if _is(_at(toks, j), "op", "{"):
            return (".".join(parts), prefix, "namespace", j, True)
        return None
    if _is(t, "word", "type") and _is(_at(toks, j + 1), "word") and (_is(_at(toks, j + 2), "op", "=") or _is(_at(toks, j + 2), "op", "<")):
        k = j + 2
        if _is(toks[k], "op", "<"):
            close = _match(toks, k, angles=True)
            if close is None or not _is(_at(toks, close + 1), "op", "="):
                return None
            k = close + 1
        return (toks[j + 1].text, prefix, "type", k + 1, False) if k + 1 < len(toks) else None
    if _is(t, "word") and t.text in ("const", "let", "var"):
        if not _is(_at(toks, j + 1), "word"):
            return None  # destructuring defines no single name
        name = toks[j + 1].text
        k = j + 2
        if _is(_at(toks, k), "op", "!"):
            k += 1
        if _is(_at(toks, k), "op", ":"):
            k = _skip_type(toks, k + 1, ("=",))
            if k is None:
                return None
        if not _is(_at(toks, k), "op", "="):
            return None
        value = _value(toks, k + 1)
        if value is None or (value[0] == "object" and (stack and stack[-1].kind not in ("namespace", "object"))):
            return None  # an object is a definition at module level (`const nodeOps = {`), a local inside a function
        return (name, prefix, value[0], value[1], value[2])
    if default:
        value = _value(toks, j)
        return None if value is None else ("default", prefix, value[0], value[1], value[2])
    if _is(t, "word") and j == i:
        if t.text in _TEST_WORDS:
            titled = _titled(toks, i, stack)
            if titled is not None:
                return titled
        return _member(toks, i, stack)
    return None


def _member_of_class(toks: list[Token], i: int, stack: list[_Frame]) -> tuple[str, str, str, int, bool] | None:
    """A method or a field holding a function in a class body, starting at `i`."""
    prefix = stack[-1].prefix
    j = _skip_decorators(toks, i)
    if j is None:
        return None
    while _is(_at(toks, j), "word") and toks[j].text in _MODIFIERS:
        after = _at(toks, j + 1)
        if _is(after, "word") or _is(after, "op", "*") or _is(after, "op", "@") or _is(after, "op", "["):
            j += 1
        else:
            break  # a method named `get` or `static`
    if _is(_at(toks, j), "op", "*"):
        j += 1
    if not _is(_at(toks, j), "word"):
        return None  # a computed or string key, an index signature
    name = toks[j].text
    k = j + 1
    if _is(_at(toks, k), "op", "?") or _is(_at(toks, k), "op", "!"):
        k += 1
    if _is(_at(toks, k), "op", "<"):
        close = _match(toks, k, angles=True)
        if close is None:
            return None
        k = close + 1
    if _is(_at(toks, k), "op", "("):
        close = _match(toks, k)
        if close is None:
            return None
        body = _body(toks, close + 1)
        return None if body is None else (name, prefix, "function", body, True)
    if _is(_at(toks, k), "op", ":"):
        k = _skip_type(toks, k + 1, ("=",))
        if k is None:
            return None
    if not _is(_at(toks, k), "op", "="):
        return None
    value = _value(toks, k + 1)
    return None if value is None else (name, prefix, value[0], value[1], value[2])


def _member_of_object(toks: list[Token], i: int, stack: list[_Frame]) -> tuple[str, str, str, int, bool] | None:
    """A method, or a key holding a function, a class or another object, in an object literal that has a name."""
    prefix = stack[-1].prefix
    j = i
    while _is(_at(toks, j), "word") and toks[j].text in ("async", "get", "set"):
        after = _at(toks, j + 1)
        if after is not None and (after.kind in ("word", "str", "num") or _is(after, "op", "*")):
            j += 1
        else:
            break  # a key named `get`
    if _is(_at(toks, j), "op", "*"):
        j += 1
    t = _at(toks, j)
    if t is None or t.kind not in ("word", "str", "num"):
        return None  # a computed key or a spread
    name = t.text[1:-1] if t.kind == "str" else t.text
    if not name:
        return None
    k = j + 1
    if _is(_at(toks, k), "op", "<"):
        close = _match(toks, k, angles=True)
        if close is None:
            return None
        k = close + 1
    if _is(_at(toks, k), "op", "("):
        close = _match(toks, k)
        if close is None:
            return None
        body = _body(toks, close + 1)
        return None if body is None else (name, prefix, "function", body, True)
    if not _is(_at(toks, k), "op", ":"):
        return None
    value = _value(toks, k + 1)
    return None if value is None else (name, prefix, value[0], value[1], value[2])


def definitions(text: str) -> list[tuple[str, int, int]] | None:
    """Every definition of a JavaScript or TypeScript source as (dotted name, first line, last line), in source order
    with a nested definition after the one holding it; None when the source cannot be read."""
    toks = tokens(text)
    if toks is None:
        return None
    found: list[list] = []
    stack: list[_Frame] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if _is(t, "op", "{"):
            stack.append(_Frame("block", stack[-1].prefix if stack else "", None))
            i += 1
            continue
        if _is(t, "op", "}"):
            if not stack:
                return None
            frame = stack.pop()
            if frame.index is not None:
                found[frame.index][2] = t.line
            i += 1
            continue
        head = None
        kind = stack[-1].kind if stack else "module"
        if kind == "object":
            if t.kind in ("word", "str", "num"):
                head = _member_of_object(toks, i, stack)
        elif t.kind == "word" or _is(t, "op", "@"):
            if kind == "class":
                head = _member_of_class(toks, i, stack)
            elif kind not in ("interface", "enum"):
                head = _statement(toks, i, stack)
        if head is None:
            i += 1
            continue
        name, prefix, kind, body, block = head
        full = prefix + name
        index = len(found)
        found.append([full, t.line, None])
        if block:
            stack.append(_Frame(kind, full + ".", index))
            i = body + 1
        else:
            found[index][2] = toks[_expression_end(toks, body)].end
            i = body
    if stack:
        return None
    return [(name, start, end) for name, start, end in found]
