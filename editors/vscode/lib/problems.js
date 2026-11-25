// What `tessri check` found, as one problem per file: the editor shows each at the file it is about, at the line that
// names the missing file when one does. Nothing here is a judgement of the editor's: the kind, the severity and the
// words come from the check result; this module only turns findings about groups of files into one entry per file.

"use strict";

const path = require("path");

const SEVERITIES = ["block", "warn", "info"];
const PROBLEM_KINDS = new Set(["dangling-import", "dangling-reference", "new-orphan", "new-cycle", "cycle-grew", "no-active-owner"]);

const CODE = (p) => `\`${p}\``;
const list = (items) => items.map(CODE).join(", ");

/** The strings a line may carry when it names `rel`, surest first: the path, the dotted module of a Python file, the
 * path without its extension, the base name as a relative import ends (`/name"`), the base name. */
function needles(rel) {
  const ext = path.posix.extname(rel);
  const bare = ext ? rel.slice(0, -ext.length) : rel;
  const dotted = ext === ".py" ? bare.replace(/\/__init__$/, "").split("/").join(".") : "";
  const stem = path.posix.basename(bare);
  const out = [rel, dotted.length >= 3 ? dotted : "", bare, `/${stem}"`, `/${stem}'`, path.posix.basename(rel)];
  return [...new Set(out.filter((s) => s && s.length > 1))];
}

function severityOf(findings, id, fallback) {
  const hit = findings.find((f) => f.id === id);
  return hit && SEVERITIES.includes(hit.severity) ? hit.severity : fallback;
}

function wasMoved(row) {
  return typeof row.moved_to === "string" && row.moved_to;
}

const REFERENCE = {
  config: ["this config still names it: wiring that now points at a file that is gone.", "Update the name in the same change, or restore the file."],
  doc: ["this document still names it: a sentence that is now wrong.", "Update the documentation in the same change."],
  code: ["a string in this file still names it: the analysis's guess that the file is loaded at run time, not a statement the code made.", "Check whether it does; if so, update the name in the same change or restore the file."],
};

/** One problem per (finding, file) from a `tessri check` result; empty for a result without findings or code changes. */
function problems(check) {
  const findings = Array.isArray(check && check.findings) ? check.findings : [];
  const out = [];
  const add = (p) => out.push({ ...p, needles: p.needles || [] });

  for (const row of check.dangling_imports || []) {
    const severity = severityOf(findings, `dangling-import:${row.deleted}`, "block");
    for (const importer of row.importers || []) {
      const message = wasMoved(row)
        ? `${CODE(row.deleted)} was moved to ${CODE(row.moved_to)}, and this file still imports it under its old name. Update the import to the new path in the same change.`
        : `${CODE(row.deleted)} was deleted, and this file still imports it. Restore the file, or update the import in the same change.`;
      add({ path: importer, severity, kind: "dangling-import", message, needles: needles(row.deleted) });
    }
  }

  for (const row of check.dangling_references || []) {
    const severity = severityOf(findings, `dangling-reference:${row.deleted}`, "warn");
    for (const ref of row.referrers || []) {
      const cls = ref.kind === "config" || ref.kind === "doc" ? ref.kind : "code";
      const [what, mend] = REFERENCE[cls];
      const head = wasMoved(row) ? `${CODE(row.deleted)} was moved to ${CODE(row.moved_to)}, and ${what.replace("still names it", "still names it by its old name")}` : `${CODE(row.deleted)} was deleted, and ${what}`;
      add({ path: ref.path, severity, kind: "dangling-reference", message: `${head} ${mend}`, needles: needles(row.deleted) });
    }
  }

  const orphans = (check.orphans && check.orphans.new) || [];
  for (const row of orphans) {
    const severity = severityOf(findings, `new-orphan:${row.how}`, "warn");
    const message =
      row.how === "stranded"
        ? `Nothing reaches this file any more: the change removed the last way to it${row.was_reached_from && row.was_reached_from.length ? ` (it was reached from ${row.was_reached_from.map((s) => `${CODE(s)}${row.reached_kinds && row.reached_kinds[s] && row.reached_kinds[s] !== "import" ? ` (${row.reached_kinds[s]})` : ""}`).join(", ")})` : ""}. Delete it with the change, or restore the link.`
        : "Nothing reaches this file: no entry point, test or config imports it, so as far as the analysis can tell it is dead on arrival. Import it from where it is meant to be used, add a test that does, or drop it.";
    add({ path: row.path, severity, kind: "new-orphan", message });
  }

  const cycles = check.cycles || {};
  for (const [kind, rows] of [["new-cycle", cycles.new || []], ["cycle-grew", cycles.grown || []]]) {
    for (const row of rows) {
      const modules = Array.isArray(row.modules) ? row.modules : [];
      const severity = severityOf(findings, `${kind}:${modules.slice(0, 4).join("+")}`, "warn");
      const seen = new Set();
      for (const edge of row.closing || []) {
        const example = (edge.examples || [])[0];
        if (!example || !example[0] || seen.has(example[0])) continue;
        seen.add(example[0]);
        const loop = kind === "cycle-grew" && row.added_modules ? `draws ${list(row.added_modules)} into an existing cycle with ${list(modules.filter((m) => !row.added_modules.includes(m)).slice(0, 6))}` : `closes a cycle: modules ${list(modules.slice(0, 6))} now depend on each other`;
        add({ path: example[0], severity, kind, message: `This import ${loop}, through ${CODE(example[1])}. Remove or invert the new dependency, or move what both need into a module they both depend on.`, needles: example[1] ? needles(example[1]) : [] });
      }
    }
  }

  for (const row of check.unowned || []) {
    const severity = severityOf(findings, "no-active-owner:changed", "warn");
    const who = row.last_owner ? `its last maintainer, ${row.last_owner}, has not committed in ${row.owner_idle_days} days` : "its history names nobody who is still active";
    add({ path: row.path, severity, kind: "no-active-owner", message: `Nobody active maintains this file: ${who}. Have someone who knows the code look before merging, or assign an owner.` });
  }

  const rank = (s) => SEVERITIES.indexOf(s);
  return out.sort((a, b) => rank(a.severity) - rank(b.severity) || a.path.localeCompare(b.path) || a.kind.localeCompare(b.kind));
}

/** The 0-based line of the first needle a text carries, in needle order; 0 when none does. */
function lineOf(text, needlesToFind) {
  const lines = String(text || "").split(/\r?\n/);
  for (const needle of needlesToFind || []) {
    const at = lines.findIndex((l) => l.includes(needle));
    if (at >= 0) return at;
  }
  return 0;
}

/** The status bar's words for a set of problems: counts by severity, in the order the check ranks them. */
function summary(items) {
  const counts = {};
  for (const p of items) counts[p.severity] = (counts[p.severity] || 0) + 1;
  const parts = SEVERITIES.filter((s) => counts[s]).map((s) => `${counts[s]} ${s}`);
  return parts.length ? parts.join(" · ") : "no findings";
}

module.exports = { problems, needles, lineOf, summary, SEVERITIES, PROBLEM_KINDS };
