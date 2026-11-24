// What the editor shows about one file, in words, from the JSON of `tessri why` and `tessri impact`: the code
// lens over a file and the hover over a definition. Every number is one of those two objects' own; nothing is
// computed here, so what the hover says is what `tessri why <path>` prints.

"use strict";

const REACH = {
  prod: "reachable from a production entry point",
  test: "reachable only from tests",
  none: "nothing reaches it: no entry point, test or config reference",
};

function many(n, one, several) {
  return `${n} ${n === 1 ? one : several || `${one}s`}`;
}

/** "A 70%, B 30%" for the people of why's `owners` or impact's `owners`; null when there is nobody. */
function people(owners, limit = 3) {
  const list = Array.isArray(owners) ? owners : owners && Array.isArray(owners.people) ? owners.people : [];
  if (!list.length) return null;
  const shown = list.slice(0, limit).map((p) => `${p.name} ${p.share}%${p.silent ? ` (silent ${p.idle_days}d)` : ""}`);
  const more = list.length - shown.length;
  return shown.join(", ") + (more > 0 ? ` and ${more} more` : "");
}

function maintainers(why, impact) {
  const owners = why ? why.owners : impact ? impact.owners : null;
  if (owners === null || owners === undefined) return null;
  const who = people(owners);
  if (!who) return "no usable history";
  return (why && why.owners && why.owners.state === "no-active-owner" ? "no active owner; last " : "maintained by ") + who;
}

function history(why) {
  if (!why || !why.git) return null;
  return why.git.tracked ? `last commit ${why.git.last_commit}` : "no git history yet";
}

/** The code lens over a file, or null when neither object is there. */
function lens(why, impact) {
  const parts = [];
  if (impact) {
    const d = impact.dependents;
    parts.push(d.files ? `${many(d.files, "dependent")}${d.direct ? ` (${d.direct} direct)` : ""}` : "no dependents");
    parts.push(impact.tests.files ? many(impact.tests.files, "candidate test") : "no candidate test");
  }
  const who = maintainers(why, impact);
  if (who) parts.push(who);
  const when = history(why);
  if (when) parts.push(when);
  return parts.length ? `Tessri: ${parts.join(" · ")}` : null;
}

/**
 * The definition of why's `definitions` that is named `name` (or ends in `.name`) and holds the 1-based `line`:
 * the innermost when several do, null when none or when the definitions were not read.
 */
function definitionFor(why, name, line) {
  const d = why && why.definitions;
  if (!d || !d.available) return null;
  let best = null;
  for (const item of d.items) {
    if (item.start <= line && line <= item.end && (item.name === name || item.name.endsWith(`.${name}`)) && (!best || item.end - item.start < best.end - best.start)) best = item;
  }
  return best;
}

function tests(n) {
  return n === 1 ? "the 1 test that reaches the file" : `the ${n} tests that reach the file`;
}

/** What the reaching tests say about one definition, or null when there is nothing to say. */
function named(why, item) {
  if (!item || !why || !why.definitions) return null;
  const d = why.definitions;
  if (item.named_in === null) return "Not searched by name in the tests: too short, private or too common.";
  if (!d.tests) return null; // the dependents line already says that no test reaches the file
  const unread = d.unread.length ? ` ${many(d.unread.length, "reaching test")} could not be read.` : "";
  if (!item.named_in.length) return `Named in none of ${tests(d.tests)}.${unread}`;
  const shown = item.named_in.slice(0, 3).map((t) => `\`${t}\``);
  const more = item.named_in.length - shown.length;
  return `Named in ${shown.join(", ")}${more > 0 ? ` and ${more} more` : ""}, of ${tests(d.tests)}.${unread}`;
}

/**
 * The hover over a definition named `name` in the file `rel`: Markdown, a paragraph per fact. `item` is the
 * definition's entry in why's `definitions`, when there is one; `links` holds the `command:` URIs for the two
 * commands; without it the last paragraph is left out.
 */
function hover(name, rel, why, impact, links, item) {
  if (!why && !impact) return null;
  const out = [`**\`${name}\`** · \`${rel}\`${why && why.file && why.file.test ? " · test file" : ""}`];
  const mention = named(why, item);
  if (mention) out.push(mention);
  if (why && why.verdict) {
    const status = why.verdict.status ? `${why.verdict.status}: ` : "";
    const reach = why.file && why.file.analyzer === null ? `not analysed (no analyzer for ${why.file.language})` : REACH[why.verdict.reachability] || why.verdict.reachability;
    out.push(status + reach);
  }
  const who = maintainers(why, impact);
  const when = why && why.git ? (why.git.tracked ? `last commit ${why.git.last_commit}, ${many(why.git.commits_year, "commit")} by ${many(why.git.authors_year, "author")} in a year` : "no git history yet (new or untracked)") : null;
  const line = [who ? who[0].toUpperCase() + who.slice(1) : null, when].filter(Boolean).join(" · ");
  if (line) out.push(line);
  if (impact) {
    const d = impact.dependents;
    const t = impact.tests;
    const depends = d.files ? `${many(d.files, "code file")} depend${d.files === 1 ? "s" : ""} on it${d.direct ? `, ${d.direct} directly` : ""}` : "No code file depends on it";
    const reach = t.files ? `${many(t.files, "candidate test")} reach${t.files === 1 ? "es" : ""} it${t.direct ? `, ${t.direct} directly` : ""}` : "no test reaches it";
    out.push(`${depends} · ${reach}`);
    if (t.files) out.push(mention && item.named_in !== null ? "_Named means the identifier appears in the test's code: a mention, not an assertion. Candidate tests are paths, not runs._" : "_Candidate tests are paths that reach the file, not runs._");
  }
  if (links) out.push(`[Why this file](${links.why}) · [What a change here can reach](${links.impact})`);
  return out.join("\n\n");
}

module.exports = { lens, hover, definitionFor, named, people, many, REACH };
