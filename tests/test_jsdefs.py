"""`tessri/analyzers/jsdefs.py`: the definitions of a JavaScript or TypeScript source with their line spans, read
without a parser."""

import unittest

from tessri.analyzers import jsdefs

JS = '''import { a } from "./a";
// comment with { brace
const LIMIT = 3;

export function helper(x) {
  return x + 1;
}

export default class Shape extends Base {
  static kind = "shape";
  #secret = 1;

  constructor(sides) {
    super();
    this.sides = sides;
    this.onClick = () => { this.sides++; };
  }

  area() {
    return 0;
  }

  get name() { return "shape"; }

  async *walk() { yield 1; }

  handle = (e) => {
    return e;
  };
}

const oldWay = function () { return helper(0); };
let arrow = (a, b) => a + b;
var tagged = async x => x;

function outer() {
  function inner() { return 1; }
  const deep = () => 2;
  return inner() + deep();
}

Shape.prototype.extra = function () { return 1; };
exports.run = () => run();
module.exports = function main() {};

describe("x", () => {
  it("y", () => {
    function helperInTest() { return "it's" }
  });
});
'''

TS = '''export interface Props<T extends { id: string }> {
  items: T[];
  render(item: T): string;
}

export type Handler = (e: Event) => void;
type Union =
  | "a"
  | "b";

export enum Color { Red, Green }

export namespace Util.Inner {
  export function fmt(x: number): string { return `${x}`; }
}

@Component({ selector: "x" })
export class Widget<T> implements OnInit {
  @Input() value?: T;
  private readonly cache = new Map<string, T>();

  public async load(id: string): Promise<{ ok: boolean }> {
    return { ok: true };
  }

  abstract render(): void;

  protected static of<U>(x: U): Widget<U> { return new Widget(); }
}

export function over(a: string): void;
export function over(a: number): void;
export function over(a: any): void {
  console.log(a);
}

export const useThing = <T,>(x: T): T => x;
export const api: Api = {
  get() { return 1; },
};
export default async () => {
  return 1;
};
declare module "foo" {
  export function bar(): void;
}
'''

TSX = '''import React from "react";

export default function App() {
  const [n, setN] = React.useState(0);
  const onClick = () => setN(n + 1);
  return (
    <div className="app" onClick={onClick}>
      <p>It's {n} and {n > 1 ? <b>big</b> : "small"}</p>
      <List items={[1, 2].map((i) => <li key={i}>{i}</li>)} />
      <br/>
    </div>
  );
}

export const Row = ({ a, b }: { a: number; b: string }) => <tr><td>{a}</td><td>{b}</td></tr>;

const Styled = styled.div`
  color: ${(p) => p.color};
`;
'''

OBJECTS = '''export const nodeOps = {
  insert: (child, parent, anchor) => {
    parent.insertBefore(child, anchor || null)
  },
  remove(child) {
    child.remove()
  },
  async *walk() {},
  "quoted-key": function () {},
  nested: { deep() { return 1 } },
  get size() { return 1 },
  plain: 1,
  [computed]: () => 2,
  ...spread,
}
export default {
  data() { return { n: 1 } },
  methods: { go() {}, stop: () => {} },
}
module.exports = { run() {} };
function local() {
  const opts = { a() {} };
  sref.value = { a: 2 };
  return opts;
}
'''

NO_SEMICOLONS = '''let dummy: number
const f = () => 1
export function over(a: string): void
export function over(a: any): void {
  return
}
class A {
  value: T
  handle = () => {}
  abstract render(): void
  protected static of<U>(x: U): A { return new A() }
}
'''


def spans(text):
    return {name: (start, end) for name, start, end in jsdefs.definitions(text)}


def names(text):
    return [name for name, _, _ in jsdefs.definitions(text)]


class JavaScriptTest(unittest.TestCase):
    def test_functions_classes_methods_and_assigned_functions_in_source_order(self):
        self.assertEqual(names(JS)[:12], ["helper", "Shape", "Shape.constructor", "Shape.onClick", "Shape.area", "Shape.name", "Shape.walk", "Shape.handle", "oldWay", "arrow", "tagged", "outer"])
        s = spans(JS)
        self.assertEqual(s["helper"], (5, 7))
        self.assertEqual(s["Shape"], (9, 30))
        self.assertEqual(s["Shape.constructor"], (13, 17))
        self.assertEqual(s["Shape.handle"], (27, 29))  # a class field holding an arrow function
        self.assertEqual(s["arrow"], (33, 33))  # an arrow with an expression body ends with its statement

    def test_a_definition_inside_another_is_named_through_it_and_a_plain_callback_has_no_name(self):
        s = spans(JS)
        self.assertEqual((s["outer"], s["outer.inner"], s["outer.deep"]), ((36, 40), (37, 37), (38, 38)))
        self.assertEqual(s["Shape.onClick"], (16, 16))  # `this.handler = ...` in a constructor belongs to the class
        self.assertEqual((s["x"], s["x.y"], s["x.y.helperInTest"]), ((46, 50), (47, 49), (48, 48)))  # test titles name their callbacks
        self.assertEqual(spans("run(() => {\n  function later() {}\n})\n"), {"later": (2, 2)})  # any other callback: nothing to name it through

    def test_member_assignments_name_what_a_module_exports(self):
        s = spans(JS)
        self.assertEqual(s["Shape.extra"], (42, 42))  # `.prototype` is dropped
        self.assertEqual(s["run"], (43, 43))  # `exports.run`
        self.assertEqual(s["module.exports"], (44, 44))
        self.assertNotIn("LIMIT", s)  # a plain value is not a definition


class TypeScriptTest(unittest.TestCase):
    def test_interfaces_types_enums_namespaces_and_decorated_classes(self):
        s = spans(TS)
        self.assertEqual(s["Props"], (1, 4))  # a generic with an object type in its constraint
        self.assertEqual(s["Handler"], (6, 6))
        self.assertEqual(s["Union"], (7, 9))  # a union continued across lines
        self.assertEqual(s["Color"], (11, 11))
        self.assertEqual((s["Util.Inner"], s["Util.Inner.fmt"]), ((13, 15), (14, 14)))
        self.assertEqual(s["Widget"], (17, 29))  # the decorator line starts it
        self.assertEqual(s["Widget.load"], (22, 24))  # a return type with an object type in it
        self.assertEqual(s["Widget.of"], (28, 28))

    def test_signatures_without_bodies_are_not_definitions(self):
        s = spans(TS)
        self.assertEqual(s["over"], (33, 35))  # the implementation, not the overloads
        self.assertNotIn("Widget.render", s)  # abstract
        self.assertNotIn("Widget.value", s)  # a field with no function in it
        self.assertNotIn("bar", s)  # `declare module` holds declarations only

    def test_generic_arrows_default_exports_and_objects_typed_by_annotation(self):
        s = spans(TS)
        self.assertEqual(s["useThing"], (37, 37))
        self.assertEqual(s["default"], (41, 43))
        self.assertEqual((s["api"], s["api.get"]), ((38, 40), (39, 39)))


class JSXTest(unittest.TestCase):
    def test_components_and_what_jsx_makes_ambiguous(self):
        s = spans(TSX)
        self.assertEqual((s["App"], s["App.onClick"], s["Row"]), ((3, 13), (5, 5), (15, 15)))
        self.assertNotIn("Styled", s)  # a tagged template is not a function

    def test_an_apostrophe_in_text_opens_no_string_and_a_slash_between_elements_is_no_regex(self):
        text = "const C = () => (\n  <p>Don't {worry}, it's <b>fine</b> {a} / {b}</p>\n);\nfunction F() { return <span>Don't have it? <a href=\"x\" style={{ color: 'red' }}>get</a></span> }\n"
        self.assertEqual(spans(text), {"C": (1, 3), "F": (4, 4)})

    def test_a_regex_after_an_arrow_is_a_regex_even_with_a_backtick_in_it(self):
        text = "const ok = values.every((value) => /^[!#$%&'*+\\-.^_`|~0-9A-Za-z]+$/.test(value));\nfunction g() {}\n"
        self.assertEqual(spans(text), {"g": (2, 2)})


class ObjectTest(unittest.TestCase):
    def test_an_object_at_module_level_names_its_methods_and_function_valued_keys(self):
        s = spans(OBJECTS)
        self.assertEqual(s["nodeOps"], (1, 15))
        self.assertEqual((s["nodeOps.insert"], s["nodeOps.remove"], s["nodeOps.walk"]), ((2, 4), (5, 7), (8, 8)))
        self.assertEqual(s["nodeOps.quoted-key"], (9, 9))
        self.assertEqual((s["nodeOps.nested"], s["nodeOps.nested.deep"]), ((10, 10), (10, 10)))
        self.assertEqual(s["nodeOps.size"], (11, 11))
        self.assertFalse({"nodeOps.plain", "nodeOps.computed", "nodeOps.spread"} & set(s))

    def test_a_default_export_and_module_exports_are_objects_with_names(self):
        s = spans(OBJECTS)
        self.assertEqual((s["default"], s["default.data"], s["default.methods.go"], s["default.methods.stop"]), ((16, 19), (17, 17), (18, 18), (18, 18)))
        self.assertEqual((s["module.exports"], s["module.exports.run"]), ((20, 20), (20, 20)))

    def test_a_local_object_and_an_assigned_property_are_statements_not_definitions(self):
        s = spans(OBJECTS)
        self.assertEqual(s["local"], (21, 25))
        self.assertFalse({"local.opts", "local.opts.a", "sref.value", "local.sref.value"} & set(s))


class TestTitleTest(unittest.TestCase):
    def test_a_test_callback_is_named_by_its_title_and_nested_through_its_suite(self):
        text = (
            "describe('ref', () => {\n"
            "  it.only('should   unwrap  nested values', async function () {\n"
            "    const a = () => 1\n"
            "  })\n"
            "  test(`a ${dynamic} title`, () => {})\n"
            "  test.each([1])('each %s', () => {})\n"
            "})\n"
            "it('x'.repeat(2), () => {})\n"
        )
        self.assertEqual(spans(text), {"ref": (1, 7), "ref.should unwrap nested values": (2, 4), "ref.should unwrap nested values.a": (3, 3)})

    def test_a_long_title_is_cut(self):
        name = names("test('" + "word " * 20 + "', () => {})\n")[0]
        self.assertEqual(len(name), jsdefs.TITLE)
        self.assertTrue(name.endswith("…"))


class WithoutSemicolonsTest(unittest.TestCase):
    def test_a_line_break_that_nothing_continues_ends_the_statement(self):
        s = spans(NO_SEMICOLONS)
        self.assertEqual(s, {"f": (2, 2), "over": (4, 6), "A": (7, 12), "A.handle": (9, 9), "A.of": (11, 11)})


class UnreadableTest(unittest.TestCase):
    def test_unbalanced_braces_and_open_literals_are_none_and_an_empty_source_is_empty(self):
        self.assertIsNone(jsdefs.definitions("function f() {\n  return 1\n"))
        self.assertIsNone(jsdefs.definitions("}\n"))
        self.assertIsNone(jsdefs.definitions("const s = `abc\n"))
        self.assertIsNone(jsdefs.definitions("/* never closed\nfunction f() {}\n"))
        self.assertEqual(jsdefs.definitions(""), [])
        self.assertEqual(jsdefs.definitions("#!/usr/bin/env node\nfunction f() {}\n"), [("f", 2, 2)])


if __name__ == "__main__":
    unittest.main()
