// Tactical boards (docs/TELESTRATION_PLAN.md, M7). A board is a freeze whose
// picture is a pitch instead of the held frame: {atFrame, seconds, background}.
// Drawings made on a board carry `on: atFrame` and show only on that board;
// the clip's own drawings are hidden while a board is on screen.
import { LINES, boardLayout, viewFor } from "./pitch.js";
import { outputToSource, freezeStart, setFreeze } from "./timeline.js";
import { newId } from "./document.js";

export const THEMES = {
  grass: { name: "Grass", ground: "#2f6b3a", stripe: "#357541", line: "rgba(255, 255, 255, 0.92)" },
  light: { name: "Light", ground: "#f2f3ee", stripe: "#f2f3ee", line: "#8f948c" },
};
export const TEAMS = { home: "Home", away: "Away", other: "Other" };
export const DEFAULT_TEAM_COLOURS = { home: "#d6262e", away: "#1f5fd1", other: "#f2c200" };
export const BOARD_SECONDS = 4;

/** The board on screen at output time `t`, or null (a plain freeze or the clip). */
export const boardAt = (value, clip, t) => {
  const at = outputToSource(t, clip, value.freezes || []);
  if (at.freeze === null) return null;
  const freeze = (value.freezes || []).find((f) => f.atFrame === at.freeze);
  return freeze?.background ? freeze : null;
};

/** The drawings that show at output time `t`: a board's own drawings on a board, the clip's elsewhere. */
export const itemsAt = (value, clip, t) => {
  const board = boardAt(value, clip, t);
  return value.items.filter((item) => (board ? item.on === board.atFrame : item.on === undefined));
};

/** Draw the board picture (pitch and lines) over the whole w x h canvas. */
export const drawBoard = (ctx, w, h, background) => {
  const theme = THEMES[background.theme] || THEMES.grass;
  const layout = boardLayout(background.view === "blank" ? "full" : background.view, w / h);
  ctx.save();
  ctx.fillStyle = theme.ground;
  ctx.fillRect(0, 0, w, h);
  if (theme.stripe !== theme.ground) {
    // Mowing stripes across the length, every 5.25 m, as on most pitches.
    ctx.fillStyle = theme.stripe;
    for (let x = -52.5; x < 52.5; x += 10.5) {
      const [a] = layout.toBoard([x, 0]);
      const [b] = layout.toBoard([x + 5.25, 0]);
      ctx.fillRect(a * w, 0, (b - a) * w, h);
    }
  }
  if (background.view !== "blank") {
    ctx.strokeStyle = theme.line;
    ctx.lineWidth = Math.max(1.5, layout.metre * h * 0.14);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    LINES.forEach((line) => {
      ctx.beginPath();
      line.forEach((point, index) => {
        const [x, y] = layout.toBoard(point);
        if (index) ctx.lineTo(x * w, y * h);
        else ctx.moveTo(x * w, y * h);
      });
      ctx.stroke();
    });
  }
  ctx.restore();
};

/** Where a new board goes for source frame `frame`: that frame, or the next one without an insert. Null if none is free. */
export const boardFrame = (value, clip, frame) => {
  const taken = new Set((value.freezes || []).map((f) => f.atFrame));
  for (let at = frame; at < clip.frames; at += 1) if (!taken.has(at)) return at;
  return null;
};

/** A token drawing: a numbered disc in its team's colour, on board `on`. */
export const newToken = (point, { team = "home", label = "", name = "", colours = DEFAULT_TEAM_COLOURS, from, to, on }) => {
  const item = {
    id: newId(),
    kind: "token",
    points: [point.map((v) => Math.round(v * 1e5) / 1e5)],
    style: { fill: colours[team] || DEFAULT_TEAM_COLOURS[team], stroke: "#ffffff", color: textOn(colours[team] || DEFAULT_TEAM_COLOURS[team]), size: 34, width: 2 },
    show: { from: Math.round(from * 1000) / 1000, to: Math.round(to * 1000) / 1000, animate: "none" },
    team,
    label: String(label).slice(0, 3),
  };
  if (name) item.name = String(name).slice(0, 30);
  if (on !== undefined) item.on = on;
  return item;
};

/** Black or white, whichever reads better on `hex`. */
export const textOn = (hex) => {
  const n = parseInt(String(hex).slice(1), 16);
  const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255];
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#171817" : "#ffffff";
};

/**
 * The document with a board inserted on source frame `frame` for `seconds`, and `tokens`
 * (built by `makeTokens(from, to)` once the board's time is known) placed on it.
 */
export const addBoard = (value, clip, frame, seconds, background, makeTokens = () => []) => {
  const withFreeze = setFreeze(value, clip, frame, seconds);
  const freezes = withFreeze.freezes.map((f) => (f.atFrame === frame ? { ...f, background } : f));
  const from = freezeStart(frame, clip, freezes);
  const to = from + seconds;
  const tokens = makeTokens(from, to).map((token) => ({ ...token, on: frame }));
  return { ...withFreeze, freezes, items: [...withFreeze.items, ...tokens] };
};

/** The document without the insert on `frame`, and without the drawings that belonged to it. */
export const removeInsert = (value, clip, frame) => {
  const next = setFreeze(value, clip, frame, 0);
  return { ...next, items: next.items.filter((item) => item.on !== frame) };
};

/** The board on `frame` with `patch` applied to its background (view, theme, colours). */
export const changeBoard = (value, frame, patch) => ({
  ...value,
  freezes: (value.freezes || []).map((f) => (f.atFrame === frame && f.background ? { ...f, background: { ...f.background, ...patch } } : f)),
});

/** The board on `frame` shown as `view`: its drawings keep their place on the pitch. */
export const changeBoardView = (value, frame, view, aspect) => {
  const board = (value.freezes || []).find((f) => f.atFrame === frame && f.background);
  if (!board || board.background.view === view) return value;
  const layoutOf = (name) => boardLayout(name === "blank" ? "full" : name, aspect);
  const [before, after] = [layoutOf(board.background.view), layoutOf(view)];
  const move = (point) => (Array.isArray(point)
    ? after.toBoard(before.toPitch(point)).map((v) => Math.round(Math.min(1.5, Math.max(-0.5, v)) * 1e5) / 1e5)
    : point);
  const next = changeBoard(value, frame, { view });
  return { ...next, items: next.items.map((item) => (item.on === frame ? { ...item, points: item.points.map(move) } : item)) };
};

/**
 * Tokens for the players found on a frame (players.find_players), placed on a board through
 * the calibration. Players whose feet map off the pitch are left out. Returns
 * {view, tokens(from, to), placed, skipped}.
 */
export const tokensFromPlayers = (players, calibration, aspect, colours) => {
  const onPitch = [];
  let skipped = 0;
  players.forEach((player) => {
    const metres = calibration.toPitch([player.box[0], player.box[1]]);
    if (!metres || Math.abs(metres[0]) > 52.5 + 3 || Math.abs(metres[1]) > 34 + 3) skipped += 1;
    else onPitch.push({ metres, team: ["home", "away", "other"][player.team] || "other" });
  });
  const view = viewFor(onPitch.map((entry) => entry.metres), aspect);
  const layout = boardLayout(view, aspect);
  return {
    view,
    placed: onPitch.length,
    skipped,
    tokens: (from, to) => onPitch.map(({ metres, team }) => newToken(layout.toBoard(metres), { team, colours, from, to })),
  };
};

// ---------------------------------------------------------------------------
// Moving boards (M8). A board token's `moves` are keys [seconds from the board's
// start, x, y]; it starts at its point, glides from key to key and holds.
// ---------------------------------------------------------------------------
export const MOVE_SECONDS = 3; // added to a board for each "move to a later frame": glide 2 s, then hold 1 s
export const GLIDE_SECONDS = 2;
const MATCH_METRES = 20;
const easeInOut = (p) => (p < 0.5 ? 2 * p * p : 1 - (-2 * p + 2) ** 2 / 2);
const round5 = (v) => Math.round(v * 1e5) / 1e5;
const round3 = (v) => Math.round(v * 1000) / 1000;

/** The keys of a token, its start included: [[0, x, y], ...moves]. */
const keysOf = (item) => [[0, ...item.points[0]], ...(item.moves || [])];

/** Where token `item` is `seconds` after its board starts. */
export const positionAt = (item, seconds) => {
  const keys = keysOf(item);
  if (seconds <= 0 || keys.length === 1) return keys[0].slice(1);
  for (let i = 1; i < keys.length; i += 1) {
    const [s1, x1, y1] = keys[i];
    if (seconds < s1) {
      const [s0, x0, y0] = keys[i - 1];
      const p = easeInOut((seconds - s0) / (s1 - s0));
      return [x0 + (x1 - x0) * p, y0 + (y1 - y0) * p];
    }
  }
  return keys[keys.length - 1].slice(1);
};

/** The drawing as it stands at output time `t`: board tokens that move are placed for that moment. */
export const placedAt = (value, clip, item, t) => {
  if (!item.moves?.length || item.on === undefined) return item;
  const seconds = t - freezeStart(item.on, clip, value.freezes || []);
  return { ...item, points: [positionAt(item, seconds)] };
};

/** The token with its place `seconds` into the board set to `point`: the start, or a key there. */
export const setMove = (item, seconds, point) => {
  const at = point.map(round5);
  if (seconds < 0.05) return { ...item, points: [at] };
  const kept = (item.moves || []).filter(([s]) => Math.abs(s - seconds) >= 0.05);
  const moves = [...kept, [round3(seconds), ...at]].sort((a, b) => a[0] - b[0]);
  return { ...item, moves };
};

/** The token without its moves (it stays where it starts). */
export const clearMoves = (item) => {
  const { moves, ...rest } = item;
  return rest;
};

/**
 * Pairs of (token index, player index) of the same team, nearest first, within 20 m.
 * `tokens` and `players` are [{team, metres: [x, y]}].
 */
export const matchPlayers = (tokens, players, limit = MATCH_METRES) => {
  const pairs = [];
  tokens.forEach((token, i) => players.forEach((player, j) => {
    if (token.team !== player.team) return;
    const distance = Math.hypot(token.metres[0] - player.metres[0], token.metres[1] - player.metres[1]);
    if (distance <= limit) pairs.push([distance, i, j]);
  }));
  pairs.sort((a, b) => a[0] - b[0]);
  const usedTokens = new Set();
  const usedPlayers = new Set();
  const matched = [];
  pairs.forEach(([, i, j]) => {
    if (usedTokens.has(i) || usedPlayers.has(j)) return;
    usedTokens.add(i);
    usedPlayers.add(j);
    matched.push([i, j]);
  });
  return matched;
};

/**
 * The board on `frame` grown by MOVE_SECONDS, with its tokens gliding to `players`
 * ([{team, metres}], found on a later frame and mapped to the pitch). Matched tokens hold,
 * glide over GLIDE_SECONDS and hold; new players appear when the glide ends; tokens with no
 * match stay put. Returns {value, matched, added, kept}.
 */
export const moveBoard = (value, clip, frame, players, aspect, colours = DEFAULT_TEAM_COLOURS) => {
  const board = (value.freezes || []).find((f) => f.atFrame === frame && f.background);
  if (!board) return { value, matched: 0, added: 0, kept: 0 };
  const layout = boardLayout(board.background.view === "blank" ? "full" : board.background.view, aspect);
  const tokens = value.items.filter((item) => item.on === frame && item.kind === "token");
  const before = board.seconds;
  const start = Math.max(0, before - (MOVE_SECONDS - GLIDE_SECONDS));
  const end = start + GLIDE_SECONDS;
  const pairs = matchPlayers(
    tokens.map((token) => ({ team: token.team, metres: layout.toPitch(positionAt(token, before)) })),
    players,
  );
  const target = new Map(pairs.map(([i, j]) => [tokens[i].id, layout.toBoard(players[j].metres)]));
  const grown = setFreeze(value, clip, frame, before + MOVE_SECONDS);
  const boardStart = freezeStart(frame, clip, grown.freezes);
  const items = grown.items.map((item) => {
    const to = target.get(item.id);
    if (!to) return item;
    // A key the analyst set late in the board is kept: the glide starts after it.
    const from = Math.max(start, ...(item.moves || []).map(([s]) => s));
    return setMove(setMove(item, from, positionAt(item, before)), from + GLIDE_SECONDS, to);
  });
  const taken = new Set(pairs.map(([, j]) => j));
  const added = players.filter((_, j) => !taken.has(j)).map((player) => ({
    ...newToken(layout.toBoard(player.metres), { team: player.team, colours, from: boardStart + end, to: boardStart + before + MOVE_SECONDS }),
    on: frame,
  }));
  return { value: { ...grown, items: [...items, ...added] }, matched: pairs.length, added: added.length, kept: tokens.length - pairs.length };
};

/** Players found on a frame (players.find_players) as [{team, metres}] on the pitch; off-pitch ones dropped. */
export const playersOnPitch = (players, calibration) => players.flatMap((player) => {
  const metres = calibration.toPitch([player.box[0], player.box[1]]);
  if (!metres || Math.abs(metres[0]) > 52.5 + 3 || Math.abs(metres[1]) > 34 + 3) return [];
  return [{ metres, team: ["home", "away", "other"][player.team] || "other" }];
});
