// The Annotate tab's session summary (ui/annotate/library.js).
import assert from "node:assert/strict";
import { test } from "node:test";

// ui/projects.js (imported by both) wires page listeners when it loads.
globalThis.document ??= { querySelectorAll: () => [], addEventListener() {} };
globalThis.window ??= { addEventListener() {} };
const { editorUrl, sessionSummary } = await import("../ui/annotate/library.js");

test("a session sums up its clips; one clip shows its length instead of a count", () => {
  const clip = (duration, drawings) => ({ id: "c", name: "Clip", duration, drawings });
  const many = sessionSummary({ clips: [clip(12, 3), clip(20, 0), clip(9, 1)], updated_at: "not a date" });
  assert.equal(many, "3 clips · 4 drawings");
  const one = sessionSummary({ clips: [clip(75.4, 1)], updated_at: "" });
  assert.equal(one, "1:15 · 1 drawing");
  assert.equal(editorUrl("p 1", "c&2"), "/annotate.html?project=p%201&clip=c%262");
});
