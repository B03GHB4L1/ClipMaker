// Links between a panel's codes, edited in the panel dialog: a code can start
// interval codes (for the same or the other team), stop interval codes, and add
// the panel's tags. app/coding/templates.py checks the same rules on save.
// Pure functions, so tests/code.test.mjs can check them.

export const LINK_LIMITS = { starts: 4, stops: 4, tags: 10 };

/** The interval codes a code may start or stop: every interval but itself. */
export const linkTargets = (codes, code) => codes.filter((other) => other.kind === "interval" && other.id !== code.id);

const tidy = (code, field, list) => {
  const next = { ...code };
  if (list.length) next[field] = list; else delete next[field];
  return next;
};

/** Start `target` for "same" or "other" team, or "" to stop starting it; null when the limit is reached. */
export const setStart = (code, target, team) => {
  const others = (code.starts || []).filter((link) => link.code !== target);
  if (!team) return tidy(code, "starts", others);
  if (others.length >= LINK_LIMITS.starts) return null;
  const at = (code.starts || []).findIndex((link) => link.code === target);
  const list = [...others];
  list.splice(at < 0 ? list.length : at, 0, { code: target, team });
  return tidy(code, "starts", list);
};

/** Turn one stop or tag link on or off; null when the limit is reached. */
export const toggleLink = (code, field, id, on) => {
  const list = (code[field] || []).filter((item) => item !== id);
  if (!on) return tidy(code, field, list);
  if (list.length < (code[field] || []).length) return code; // already on
  if (list.length >= LINK_LIMITS[field]) return null;
  return tidy(code, field, [...list, id]);
};

/** Drop links to codes and tags that left the panel, or to codes that are no longer intervals. */
export const pruneLinks = (code, codes, tags) => {
  const intervals = new Set(linkTargets(codes, code).map((other) => other.id));
  const tagIds = new Set(tags.map((tag) => tag.id));
  let next = tidy(code, "starts", (code.starts || []).filter((link) => intervals.has(link.code)));
  next = tidy(next, "stops", (code.stops || []).filter((id) => intervals.has(id)));
  return tidy(next, "tags", (code.tags || []).filter((id) => tagIds.has(id)));
};

/** "Starts Possession (other team) · Stops Build-up · Adds Header", or "" with no links. */
export const linkSummary = (code, codes, tags) => {
  const name = (list, id) => list.find((item) => item.id === id)?.label || id;
  const parts = [];
  if (code.starts?.length) parts.push(`Starts ${code.starts.map((link) => `${name(codes, link.code)}${link.team === "other" ? " (other team)" : ""}`).join(", ")}`);
  if (code.stops?.length) parts.push(`Stops ${code.stops.map((id) => name(codes, id)).join(", ")}`);
  if (code.tags?.length) parts.push(`Adds ${code.tags.map((id) => name(tags, id)).join(", ")}`);
  return parts.join(" · ");
};
