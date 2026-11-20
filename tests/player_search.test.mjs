// Players across saved matches (ui/player-search.js) and the Annotate tab's session summary (ui/annotate/library.js).
import assert from "node:assert/strict";
import { test } from "node:test";

// ui/projects.js (imported by both) wires page listeners when it loads.
globalThis.document ??= { querySelectorAll: () => [], addEventListener() {} };
globalThis.window ??= { addEventListener() {} };
const { indexPlayers, searchPlayers } = await import("../ui/player-search.js");
const { editorUrl, sessionSummary } = await import("../ui/annotate/library.js");

const match = (id, home, away, players) => ({ match: { id, home_team: home, away_team: away }, options: { team_players: players } });

test("a player in several matches is one entry that keeps each match's spelling", () => {
  const index = indexPlayers([
    match("m1", "Reims", "Strasbourg", { Strasbourg: ["Andrey Santos", "Emanuel Emegha"], Reims: ["Amadou Koné"] }),
    match("m2", "Strasbourg", "Lens", { Strasbourg: ["ANDREY SANTOS"], Lens: ["Neil El Aynaoui"] }),
  ]);
  assert.deepEqual(index.map((player) => player.name), ["Amadou Koné", "Andrey Santos", "Emanuel Emegha", "Neil El Aynaoui"]);
  const santos = index.find((player) => player.key === "andrey santos");
  assert.deepEqual(santos.matches, [
    { id: "m1", title: "Reims vs Strasbourg", names: ["Andrey Santos"] },
    { id: "m2", title: "Strasbourg vs Lens", names: ["ANDREY SANTOS"] },
  ]);
  assert.deepEqual([...santos.teams], ["Strasbourg"]);
});

test("search ignores accents, case and word order, and stops at the limit", () => {
  const index = indexPlayers([match("m1", "A", "B", { A: ["Amadou Koné", "Andrey Santos", "Kone Junior"], B: ["Santos Silva"] })]);
  assert.deepEqual(searchPlayers(index, "kone").map((p) => p.name), ["Amadou Koné", "Kone Junior"]);
  assert.deepEqual(searchPlayers(index, "SANTOS andrey").map((p) => p.name), ["Andrey Santos"]);
  assert.deepEqual(searchPlayers(index, "  ").length, 4);
  assert.equal(searchPlayers(index, "a", 2).length, 2);
  assert.deepEqual(searchPlayers(index, "zz"), []);
});

test("a session sums up its clips; one clip shows its length instead of a count", () => {
  const clip = (duration, drawings) => ({ id: "c", name: "Clip", duration, drawings });
  const many = sessionSummary({ clips: [clip(12, 3), clip(20, 0), clip(9, 1)], updated_at: "not a date" });
  assert.equal(many, "3 clips · 4 drawings");
  const one = sessionSummary({ clips: [clip(75.4, 1)], updated_at: "" });
  assert.equal(one, "1:15 · 1 drawing");
  assert.equal(editorUrl("p 1", "c&2"), "/annotate.html?project=p%201&clip=c%262");
});
