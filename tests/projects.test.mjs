import assert from "node:assert/strict";
import { test } from "node:test";

test("project autosave preserves failed patches and retries before navigation", async () => {
  const status = { textContent: "", classList: { toggle() {} } };
  globalThis.document = {
    querySelectorAll: () => [status],
    addEventListener() {},
  };
  globalThis.window = { addEventListener() {} };
  const { saveProject, flushProject, beginProjectOperation } = await import("../ui/projects.js");
  const calls = [];
  let fail = true;
  globalThis.fetch = async (path, options) => {
    const body = JSON.parse(options.body);
    calls.push(body);
    if (fail) throw new Error("Disk unavailable");
    return { ok: true, json: async () => ({ project: { id: "one", ...body } }) };
  };
  const firstPatch = { project_name: "My project" };
  const first = saveProject("one", firstPatch);
  firstPatch.project_name = "Mutated later";
  await assert.rejects(first, /Disk unavailable/);
  assert.equal(status.textContent, "Save failed");
  await assert.rejects(flushProject(), /Disk unavailable/);
  fail = false;
  const saved = await saveProject("one", { markers: { "1H": "00:00:04" } });
  await flushProject();
  assert.equal(saved.markers["1H"], "00:00:04");
  assert.deepEqual(calls.slice(-2), [
    { project_name: "My project" }, { markers: { "1H": "00:00:04" } },
  ]);
  assert.equal(status.textContent, "Saved locally");
  const finish = beginProjectOperation();
  let navigated = false;
  const switching = flushProject().then(() => { navigated = true; });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(navigated, false);
  finish();
  await switching;
  assert.equal(navigated, true);
});
