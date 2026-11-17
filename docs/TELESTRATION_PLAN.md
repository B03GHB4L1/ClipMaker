# Analyst Editor: Telestration With Player Tracking

Status: plan, not started. Written 2026-11-16; updated the same day with the
user's answers to the open questions.

## Goal

Give analysts an editor where they can draw on match footage and have drawings
follow players. Drawings can be rings, spotlights, arrows, lines, freehand,
text, and zones that change shape as players move. Analysts can freeze the
picture on a frame and animate drawings onto the frozen image. When a drawing
slips off its player (occlusion, camera cut, fast pan), the analyst drags it
back on that frame and only the rest of the clip is re-tracked. The finished
clip exports with drawings and freezes burned in.

This is a new feature. The original apps in `older versions/` have no video
telestration (their "annotations" are Plotly chart labels), so it is not a
parity item.

## Decisions (from the user, 2026-11-16)

| Question | Decision |
|---|---|
| OpenCV build-size increase (~50–90 MB per platform) | Accepted |
| Where the editor opens | A new **Annotate** button on every clip preview except the home page |
| First-release tools | Player ring/spotlight, arrows and lines, freehand, text, zones, plus freeze frames, animated drawing, and zones whose corners follow linked players |
| Text | Any text colour; any background colour or transparent; clean, legible, unobtrusive font |
| Default tracker | **OpenCV ViT tracker** (0.7 MB model, Apache 2.0), bundled in the base app as an approved exception to the model policy; standard OpenCV build, no contrib; MIL as fallback. Decided after M0 ([M0_TRACKING_SPIKE.md](M0_TRACKING_SPIKE.md)) |
| AI models | User is slightly open to them (2026-11-16). Allowed only under the proposed model policy below; the base app stays model-free through roadmap step 4. Wording for AGENTS.md still to be decided by the user |
| More Metrica tools | Reviewed in R1 ([METRICA_REVIEW.md](METRICA_REVIEW.md)); slides/board, team shape/offside/minimap and live coding/streaming moved onto the roadmap at the user's request |

## Guiding principle: light and fast

The app should stay as light and fast as possible while these additions keep
their quality and effectiveness. In practice:

- Prefer one well-chosen dependency over several. AI models only through the
  optional model pack and the model policy below; the base app stays
  model-free.
- Load the editor and its libraries only when Annotate is pressed, so the rest
  of the app starts and runs as before.
- Track at reduced resolution (540 px) and only over the spans that need it;
  re-track only after a correction.
- Keep saved data compact (one small JSON file per clip).
- Every feature taken from the Metrica review must justify its size, speed and
  complexity cost (see R1).
- Measure: editor open time, tracking speed per frame, export time and build
  size are recorded at each milestone and must not regress without a reason.

## What we learned from Metrica Nexus

From the static analysis in `Metrica Nexus/.rea-analysis/media-tracking.md`
(interfaces and settings only; no code, models or DLLs are reused):

- It has two separate tracking systems. **Seeded tracking**: the user boxes a
  player and an OpenCV-based tracker follows it, with add/update/remove calls
  for correction. **Batch tracking**: detector + appearance re-identification +
  Kalman tracker + pitch homography over a whole range.
- Seeded tracking runs on video downscaled to 540 px high at 25 fps.
- A player's position is the bottom-centre of the box (the feet) plus size.
- Per-frame records carry a "needs review" flag.
- Batch settings include gap interpolation up to 1 s and smoothing over 0.44 s.

We copy the shape of the idea (seed, track, correct, flag for review), not
their implementation.

## How it works for the analyst

1. Press **Annotate** on any clip preview. The editor opens on that clip.
2. Step frame by frame or scrub. Draw a shape.
3. To make a drawing follow a player, press **Follow player** and drag a box
   around them. That frame becomes a keyframe. The engine tracks forward to the
   next keyframe or the end of the drawing's time range, with progress on a
   timeline lane; it can be cancelled.
4. Frames the tracker is unsure about show amber ticks on the lane.
5. If a drawing drifts, drag it back on that frame. That frame becomes a new
   keyframe and only the span after it is re-tracked. The tracker never
   overwrites keyframes.
6. A detected scene cut stops tracking and asks for a new seed rather than
   letting the drawing jump to another player.
7. **Freeze**: at any frame, insert a freeze of chosen length. During the
   freeze the picture holds still while drawings animate in (draw-on, fade,
   grow), then play continues.
8. **Linked shapes**: a line, arrow or zone corner can be pinned to a tracked
   player. A zone pinned to four players stretches, shrinks and reshapes as
   they move; a line between two players shows their distance live.
9. Export the clip with drawings and freezes burned in.

## Where the Annotate button goes

Every clip preview already offers **Save clip** through `ui/save-clip.js`
(`saveClip` / `saveClipButton`). Add `annotateButton(file, name)` there so all
of these previews get it from one place:

- Filter page clip editor (`ui/filters.js`, beside the existing Save clip)
- Analyst event tab (`ui/analysis/tabs/event-tab.js`)
- Tactical tab moments and reels (`ui/analysis/tabs/tactical.js`)
- Comparison reels (`ui/analysis/tabs/comparison.js`)

The home page full-footage preview (`ui/index.html` / `ui/app.js`) does **not**
get an Annotate button (user decision, 2026-11-16).

Preview clips are temporary files the server prunes. Pressing Annotate
therefore first copies the clip into the current project
(`<project>/clips/<clip-id>.mp4`) so its annotations always have a stable
target. Then it opens the editor.

## Architecture

Fits the existing pieces: Tauri shell, vanilla JS UI in `ui/`, Python backend in
`packaging/clipmaker_api_server.py` with `JobManager` (threads + cancellation),
`atomic_json`, project store, and `/api/media/<token>` for serving video.

### Two timelines

Freezes mean the exported video is longer than the source clip, so the editor
keeps two clocks:

- **Source frames**: the frames of the clip. Tracking and player positions
  live here.
- **Output time**: what the viewer sees, i.e. source frames with freezes
  inserted. Drawing appearance, animation and freezes live here.

A small mapping function converts between them. Both the canvas preview and the
export renderer use the same mapping.

### UI (`ui/annotate.html`, `ui/annotate.js`, `ui/annotate/`, styles in `ui/annotate.css`)

- `<video>` with a `<canvas>` overlay at the same size. Coordinates are
  normalised 0–1 by frame width and height (Metrica normalises by height only).
- Rendering follows the displayed frame through `requestVideoFrameCallback`
  where available, falling back to `timeupdate`. Positions are keyed by
  **frame index** using the fps the engine reports, never by wall-clock time.
- During a freeze the video is paused on the freeze frame and the canvas keeps
  animating on a timer driven by output time.
- Tools: select, ring, spotlight, arrow, line, freehand, text, zone, freeze.
  Collapsible style panel: stroke colour, fill colour and opacity, width, text
  colour, text background colour or transparent, animation (none, draw-on,
  fade, grow) and duration. Undo/redo as a command stack.
- Timeline: source lane with freezes marked; one lane per tracked player
  showing keyframes (diamonds), review frames (amber), and tracking progress.
- Compact layout, keyboard stepping (←/→ frame, Shift for 1 s), version footer,
  narrow layout, per AGENTS.md.

### Font

The UI uses Geist Mono. For on-video text, bundle **Geist Sans** (same family,
OFL licence, as Geist Mono is already bundled under `ui/assets/fonts/` with its
OFL text). It is clean and legible at small sizes and matches the brand. The
same `.ttf` is used by the browser canvas and the export renderer so text looks
identical in both.

### Engine (`app/telestration/`)

- `tracker.py`: a `Tracker` adapter interface, `init(frame, box)` and
  `update(frame) -> (box, confidence)`. Default adapter: OpenCV ViT tracker
  (`TrackerVit`, model `vittrack.onnx`, 0.7 MB, bundled). Fallback adapter:
  OpenCV MIL (no model) if the model file is missing, with a visible notice
  that tracking quality is reduced. A future detector-assisted adapter can
  slot in without UI or data changes.
- `segments.py`: pure logic, no OpenCV. Given keyframes and tracked results,
  works out which spans need re-tracking, merges results, applies review flags
  and smoothing. Most tests live here.
- `timeline.py`: source-frame ↔ output-time mapping with freezes; shared rules
  for animation progress (same rules implemented in `editor.js`, checked by a
  test that compares both on the same inputs).
- `frames.py`: decodes the clip with the bundled ffmpeg (`imageio-ffmpeg`,
  already a dependency) at 540 px high, so tracking is fast and
  memory-bounded. Boxes are scaled back to normalised coordinates.
- `scene.py`: cheap scene-cut detection from frame histogram differences.
- Confidence (validated in M0): ViT's own loss signal, plus a **shirt-colour
  check** (upper-body colour inside the box, grass masked out, compared with
  the seed; flag when it stays different for about 0.2 s), plus an
  **out-of-frame rule** (box reaching the frame edge and shrinking). Any flag
  → amber review frame with a one-click "still right" or drag-to-fix; a run
  of flags or a scene cut → stop the segment and ask for a new seed.
- `export.py` (built in M4, replacing the planned `render.py`): the editor draws
  each overlay with the preview's own code (`ui/annotate/shapes.js`) at the
  clip's size and sends the drawn pixels (cropped, raw RGBA, in batches) only
  where the drawings change; the engine lays them over the source frames,
  holds freeze frames, inserts silence under freezes and encodes through
  `app/video_encoder.py`. Export therefore matches the preview by construction,
  and Pillow and a bundled font are not needed.

### API (added to `clipmaker_api_server.py`)

All inputs validated; clips are referenced by project clip ID, never by a raw
filesystem path.

| Route | Purpose |
|---|---|
| `POST /api/editor/clips` | Copy a preview clip (media token) into the project; returns clip ID |
| `GET /api/editor/<clip>` | Clip info (fps, size, frame count) and saved annotations |
| `POST /api/editor/<clip>` | Save annotations (atomic write) |
| `POST /api/tracking/start` | `{clip, trackId, fromFrame, toFrame, box}` → job ID |
| `GET /api/jobs/<id>` | Existing job polling; adds partial track results |
| `POST /api/jobs/<id>/cancel` | Existing cancellation |
| `POST /api/editor/<project>/<clip>/export` | Open an export of the saved clip → `{id, frames, fps, width, height}` |
| `POST /api/editor-exports/<id>/overlays` | A batch of overlays: 4-byte header length, JSON `[{frame, box}]`, then RGBA pixels |
| `POST /api/editor-exports/<id>/render` | Burn in and save to the user's folder (job, polled at `/api/editor-jobs/<id>`) |
| `POST /api/editor-exports/<id>/cancel` | Drop an export before it renders |

### Saved data

One file per edited clip, stored with the project
(`<project>/annotations/<clip-id>.json`) and referenced from the project, so it
is saved, reopened and kept independent like the rest of the project.

Every point in a shape is either **fixed** (`[x, y]` in normalised source
coordinates) or **linked** to a track (`{"track": "t1", "dx": 0, "dy": 0}`,
an offset from that player's feet). This one rule gives player rings, lines
between players, and zones whose corners follow players.

```json
{
  "version": 1,
  "clip": { "id": "...", "fps": 25, "width": 1920, "height": 1080,
            "frames": 250, "size": 12345678, "mtime": 1763300000 },
  "freezes": [ { "atFrame": 120, "seconds": 3 } ],
  "items": [
    { "id": "a1", "kind": "ring",
      "points": [ { "track": "t1", "dx": 0, "dy": 0 } ],
      "geometry": { "rx": 0.03, "ry": 0.012 },
      "style": { "stroke": "#ffd400", "width": 3 },
      "show": { "from": 0, "to": 11.5, "animate": "grow", "animSeconds": 0.4 } },
    { "id": "z1", "kind": "zone",
      "points": [ { "track": "t1", "dx": 0, "dy": 0 }, { "track": "t2", "dx": 0, "dy": 0 },
                  { "track": "t3", "dx": 0, "dy": 0 }, { "track": "t4", "dx": 0, "dy": 0 } ],
      "style": { "stroke": "#ffffff", "fill": "#2f80ed", "fillOpacity": 0.25 },
      "show": { "from": 4.8, "to": 8.0, "animate": "fade", "animSeconds": 0.3 } },
    { "id": "x1", "kind": "text", "points": [ [0.1, 0.1] ],
      "text": "Line breaks here",
      "style": { "color": "#111111", "background": "#ffd400", "size": 0.04 },
      "show": { "from": 4.8, "to": 7.8, "animate": "fade", "animSeconds": 0.2 } }
  ],
  "tracks": [
    { "id": "t1",
      "keyframes": { "0": [0.41, 0.72, 0.03, 0.11] },
      "from": 0,
      "boxes": [[0.41, 0.72, 0.03, 0.11, 0.98, 1]] }
  ]
}
```

- `show.from` / `show.to` are in **output seconds**, so drawings can appear
  during a freeze.
- Boxes are `[footX, footY, w, h, confidence, state]`, state 0 = tracked,
  1 = keyframe, 2 = needs review, 3 = lost. Ten seconds at 25 fps is 250 rows;
  plain JSON is fine.
- `background` may be `null` for transparent text.
- If a linked player is lost on a frame, shapes using it hold that player's
  last good position and the frame is flagged for review.
- If the clip file's size or mtime no longer match, the editor warns that
  drawings may be misaligned instead of silently showing them.

## Dependencies

- `opencv-python-headless` (standard build, Apache 2.0); size increase
  accepted. M0 confirmed CSRT exists only in the contrib build and is not
  needed, so contrib is not used.
- `vittrack.onnx` (0.7 MB) from `opencv/opencv_zoo`
  (`models/object_tracking_vittrack`, Apache 2.0 per its LICENSE), bundled
  with its licence text. Its README does not state the training data; check
  before release.
- (No longer needed after M4: Pillow at runtime and a bundled Geist Sans; the
  page draws text itself, so exports use the same font as the preview.)
- All three must work in the PyInstaller builds and the packaged-app launch
  test on Windows, Linux and macOS.
- The ViT tracker is a small learned model. The user approved bundling it in
  the base app as an exception to the model policy (2026-11-16); it is not
  used for filtering, so it does not touch the AI-filtering exclusion.

## AI model policy (proposed, awaiting the user's AGENTS.md wording)

The user is slightly open to AI models. To keep the app light and fast, any
model must follow these rules:

1. **Optional model pack, not in the base installer.** Exception approved
   by the user: the 0.7 MB ViT tracker model is bundled in the base app. Downloaded on first use
   with a checksum check. The core app size does not change. When the pack is
   missing, the feature says so clearly and offers to install it; it never
   fails silently (AGENTS.md).
2. **One runtime.** Start with OpenCV's DNN module, which runs many ONNX models
   and adds no dependency. Add ONNX Runtime only if measurements show it is
   needed (it also brings DirectML on Windows and CoreML on macOS).
3. **Permissive licences for code, weights and training data.** No Ultralytics
   YOLO (AGPL, including weights). Candidates believed to be Apache 2.0 or MIT,
   each to be verified before use: YOLOX, RTMDet, RT-DETR, D-FINE (detectors),
   ByteTrack (multi-object tracking, no model), OSNet (re-identification),
   MobileSAM / SAM 2 (segmentation). Football datasets such as SoccerNet often
   have research-only terms, so pitch models trained on them need checking.
4. **Clips, not full matches.** Models run on clips as background jobs with
   progress and cancel, and results are cached per clip.
5. **Output is a suggestion.** Model results feed the same keyframe-and-correct
   workflow as the classical tracker; the analyst's keyframes always win.
6. **Measured.** Each model must justify its size and speed against the
   light-and-fast principle. Target: the whole optional pack under about 50 MB
   (Metrica ships about 320 MB of models plus runtimes). Sizes in this plan are
   estimates until measured.
7. **Recorded.** AGENTS.md excludes "AI filtering"; vision models are a
   separate thing, but the allowed kinds of models should be written there
   explicitly. The user decides that wording.

The architecture already supports this: the `Tracker` adapter, per-frame
confidence/state fields and review flags work unchanged with a model-backed
tracker.

## Milestones

Each milestone is sized to fit one working session and ends verified.

**M0 – Tracking spike (go/no-go), widened.** A standalone script, no UI, on
three real clips (wide broadcast, close-up, players crossing). Compare:

- **A. Classical:** seed a box, track with CSRT at 540 px.
- **B. Model-assisted:** a small permissively licensed detector (run through
  OpenCV DNN) plus ByteTrack, with the seeded player picked from the
  detections.

For each, write an overlay video and record model/package size, time per
frame on this laptop, and how often it loses or swaps the player. Also
confirm which OpenCV package exposes CSRT. The results pick the default
tracker before any UI work. If B wins, it ships as the optional model pack
and A remains the no-pack fallback.

**M1 – Editor shell and static drawings.** Annotate button on all previews,
copying the clip into the project, frame stepping, ring/spotlight, arrows,
lines, freehand, text (colours, backgrounds, transparent), fixed-corner zones,
undo/redo, save and reopen, and screenshot export. No tracking yet.

**M2 – Freeze frames and animation.** Output-time mapping, freezes on the
timeline, draw-on/fade/grow animation, preview playback through freezes.

**M3 – Tracking and linked shapes.** Follow player, tracking job with progress
and cancel, keyframe correction with span re-tracking, review flags, scene-cut
stop, player lanes, and points linked to tracks (moving rings, player-to-player
lines, zones that reshape with their players).
Built 2026-11-16: ViT model shipped in `app/telestration/models/` (training-data
licence still to confirm before release, see its NOTICE.txt); MIL fallback with a
visible notice if the model is missing. Checked on a real clip: a follow ran to a
scene cut, a correction re-tracked only the frames after the corrected one, and
cancel, stop following and a zone corner linked to a player all behaved as planned.

**M4 – Export.** Render frames, freezes, drawings and text through the existing
encoder; cancellation; save to the user's VizorPlay folder like other clips.
Check preview and export match at sample frames. Zone fills include hatching (style `pattern`: solid, lines, cross; see ui/annotate/shapes.js), which the encoder must draw the same way.
Built 2026-11-16 (see `export.py` above). Checked on the 88 s, 50 fps test clip with a
followed player: overlays 3 s, render 31 s; a sample frame of the export differs
from the preview by 2.8/255 on average (encoding noise; 22/255 without drawings);
cancel works in both phases and leaves no files. Sending one request per frame
ran Windows out of local ports after a few exports, so overlays go in batches.

**M5 – Tracking quality.** Forward-and-backward tracking across each span,
blended so there is no jump at the next keyframe; short-gap interpolation;
light smoothing (Metrica's 0.44 s as a starting reference).

Built 2026-11-16 (`segments.blend`, `fill_gaps`, `smooth`, `finish`; `tracker.read_frames_backwards`).
When a keyframe follows the span, the engine also tracks back from it and blends the two passes,
weighting the backward pass more towards the end; where they disagree by more than 0.75 box
heights the nearer pass wins and the frame is marked for review. Holes up to 0.5 s are filled
linearly (marked for review), and a centred 0.44 s moving average smooths each run, anchored on
both keyframes so they stay where they were placed. Correcting the player on a frame re-tracks the
span after it and then the span before it. On the 50 fps test clip a 300-frame span arrives on
the next keyframe with steps under 0.4 px; a synthetic scene cut is now covered from both sides.
Costs: a span with a keyframe after it takes about twice as long (7.3 s against 3.7 s for 150
frames). A correction placed off the player still shows a few pixels' step at the end, because
the tracker re-centres on the player it sees.

**R1 – Full Metrica Nexus review. Done 2026-11-16: see
[METRICA_REVIEW.md](METRICA_REVIEW.md); its verdicts await the user's
approval before they change the milestones below.** Covers everything relevant to the analyst editor, not only
drawing tools: every annotation and drawing tool and its options, animations
and transitions, freezes and slow motion, tracking and correction workflow,
linked or player-attached shapes, timeline and keyframe UI, text and styling,
presets and templates, undo/redo, keyboard shortcuts, saved data and
interchange formats, export options, and any performance techniques visible at
the code level (downscaling, caching, worker use). Start from the existing
October notes in `.rea-analysis/` (`ui-services.md`, `media-tracking.md`,
`data-formats.md`) before any new decompiling, to keep token use low.

The output is a triage table, one row per feature: what it does, how much
analyst value it adds, its cost in app size, speed and complexity, and a
recommendation (adopt, adapt, skip). We do **not** adopt everything Metrica
has; each addition must earn its place against the lightness goal below.

## Board from this frame (M6-M8). Plan 2026-11-17, revised the same day

**Why it changed.** The first board plan (blank pitch, tokens placed by hand)
was judged not useful enough: placing players by hand is the tedious part. The
user wants the board to start from where the players really are in a frame of
the video. This pulls the single-frame part of roadmap step 6 ("board from this
frame") forward. Tracking every player through a clip stays in step 6.

**What the analyst does.** Pause on a frame, press **Board from this frame**,
click four or more known pitch points (box corners, where the halfway line
meets the touchline, and so on). A pitch board appears with a token for every
visible player in the right place, coloured by team. The analyst fixes the odd
mistake, adds anyone off-screen, numbers or names who matters, and draws.

### How it works

1. **Find the players (small model, one frame).** A person detector finds a
   box around each visible player. It runs once per board, through OpenCV DNN
   (already bundled), so it adds no runtime. Wide broadcast shots show players
   only 20-40 px tall, so the frame may be split into overlapping tiles. Which
   detector, and whether tiling is needed, is decided by the M6 spike.
2. **Split the teams (no model).** Shirt colour from the upper half of each
   box, grass pixels masked out, grouped into two teams. Referees and
   goalkeepers come out as odd colours; the analyst moves them with one click.
3. **Map video to pitch (no model).** The analyst's four or more clicks on
   known pitch points give a homography (OpenCV `findHomography`). Each
   player's feet (bottom centre of the box) map to pitch metres. An automatic
   pitch-landmark model (roadmap step 5) can replace the clicks later.

**Limits, stated in the UI.** Players outside the frame cannot appear (a
broadcast frame typically shows 10-16). Shirt numbers are not read; tokens
start without a number. Players far from the camera or overlapping may be
missed or merged.

### Tokens

Free form: a filled circle in the team colour, an optional shirt number and an
optional name under it. No formation presets. Tokens can be added, deleted and
dragged anywhere. Board looks: both grass (white lines) and light (grey lines).

### Model rules

The detector follows the "AI model policy" above: permissive licence for code
and weights (no Ultralytics YOLO), optional model pack downloaded on first use
with a checksum, never silently disabled, output is a suggestion the analyst
corrects. AGENTS.md's "AI filtering" exclusion is about filtering events and
does not cover this, but the allowed model kinds still need the user's
wording there before a model ships.

### Milestones

**M6 – Spike (go/no-go), no UI.** Standalone script, outside the app, on the
user's clips, CPU only:
- Detectors: YOLOX-s (36 MB, already used in M0), plus YOLOX-Tiny and
  YOLOX-Nano if the user approves the downloads; whole frame and tiled.
- Measured on 20 frames from wide and close shots: players found against a
  count by eye, false boxes, time per frame, model size.
- Team split by shirt colour on the same frames: share of players put on the
  right team.
- Homography from hand-clicked points on a few frames: error in metres at
  known pitch points not used for the fit.
- Result in `docs/M6_BOARD_SPIKE.md` with a recommendation.
- Go if: at least 80% of visible outfield players found on wide shots, at
  least 90% of found players on the right team, under 2 s per board on this
  laptop, model pack under 50 MB.

Done 2026-11-17, **go**: see [M6_BOARD_SPIKE.md](M6_BOARD_SPIKE.md). YOLOX-Nano
(3.7 MB) on six tiles found 93% of players on 17 wide frames in 0.47 s;
shirt hue put about 94% on the right team; the homography (simulated) is
accurate to about 0.7 m with clicks spread across the frame, so M7 shows the
fitted pitch lines on the video for checking.

**M7 – Board from this frame.** Board insert (a freeze with a pitch
background, kept in the existing `freezes` list so old projects open
unchanged); `ui/annotate/board.js` draws the pitch; calibration clicks with a
pitch diagram showing which point to click; detection job with progress and
cancel; tokens placed and coloured; correcting team, moving, adding and
deleting tokens; export with the board as background. Picture inserts (for
example a Tactical Lab map) come along, as they share the same code.

Built 2026-11-17 (board inserts, calibration, player finder, tokens, export);
**picture inserts deferred** (see below).
- Engine: `app/telestration/players.py` (YOLOX-Nano on 3 x 2 tiles through
  OpenCV DNN, feet-on-grass filter, team split by shirt hue). The model is an
  optional download offered in the editor (fixed address, size and SHA-256
  checked, written to `<data>/models` through a `.part` file, nothing kept on
  any failure, cancel supported); finding players without it asks for the
  download instead of failing. Routes: `GET /api/editor-models`,
  `POST /api/editor-models/players` (one download job at a time),
  `POST /api/editor/<project>/<clip>/players` with `{frame}`.
- Document: a board is a freeze with `background: {kind: "board", view,
  theme, fromFrame?, home?, away?}`; drawings made on it carry `on: atFrame`
  (fixed points only) and show only on that board, while the clip's drawings
  are hidden during it. Removing a board removes its drawings. Old documents
  open unchanged.
- Page: "Board from frame" opens a pitch diagram; pick a mark, click it on the
  video, drag to fine-tune with a 3x loupe. With 4 or more marks the pitch
  lines are drawn back on the video and the fit is graded in metres. Marks
  that do not pin the pitch down (for example three on the halfway line) are
  refused with a reason; this came up in testing. "Find players" runs the job
  with progress and cancel, then inserts a 4 s board (one undo step) with a
  token per player on the pitch, team colours from the shirts; players
  mapped off the pitch are left out and counted. "Empty board" skips
  detection. Token tool (K) places tokens by hand; tokens have team, shirt
  number (3 characters), optional name, colour, size. Boards have view
  (full, left half, right half, blank) and look (grass, light) in the
  "Freezes and boards" list; changing the view keeps tokens on the same pitch
  spot.
- Screenshot and export draw the board in place of the frozen frame (into
  the overlay, opaque), so the engine needed no change.
- Checked in the browser on a real broadcast clip (1024x576): 5 marks fit
  within 1.2 m, 14 players placed in 0.4 s, team and number edits saved,
  exported video shows the board for 4 s then the clip; narrow layout has no
  overflow.
- Honest limits: one match tested so far; a half view gives no zoom on a 16:9
  frame (the pitch height already sets the scale), so the board picks a half
  only on narrower frames; landmarks on the centre circle are taken at its
  axis points, which the analyst has to judge by eye; tokens are not linked
  between boards yet (M8).
- Deferred: **picture inserts** (an image, such as a Tactical Lab map, as a
  freeze background). The `background` shape leaves room for it
  (`kind: "picture"`), but it needs an upload route and stored image files,
  which is separate work.

**M8 – Moving boards.** Tokens glide between positions: either from two board
frames (the same players matched by position and team) or by tracking each
player through the clip with the M5 tracker. Export sends only the 64 px
overlay tiles that contain drawing pixels, so moving boards stay light.

M8 design (2026-11-17, at the start of M8):
- **Moves are keyframes on a token**: `moves: [[seconds, x, y], ...]`, seconds
  from the board's start, strictly increasing; the token starts at its point
  and glides (ease in and out) from key to key, then holds. Only board
  tokens move. Times are relative to the board, so changing earlier freezes
  does not break them.
- **By hand**: on a board, move the playhead to a later moment and drag a
  token: that sets its key there. The inspector shows the number of moves and
  clears them.
- **From a later frame**: "Board from frame" on a frame after a board offers
  "Move the players of board N here". Players found on that frame are matched
  to the board's tokens by team and nearest pitch position (within 20 m); the
  board grows by 3 s, the matched tokens hold, glide over 2 s and hold again.
  Unmatched new players appear at the end of the glide; unmatched tokens stay
  where they are. The counts are reported.
- **Not in M8**: following every player through a panning broadcast clip.
  That needs the camera's calibration on every frame (automatic pitch
  landmarks, roadmap step 5), so it stays in step 6.
- **Export**: when the overlay changes only in places, the page sends the
  changed 64 px tiles as a patch over the previous overlay instead of the
  whole frame; the engine keeps the overlay and applies patches in order.

Built 2026-11-17 as designed. The engine accepts `moves` only on board tokens
(at most 100, 0 < s ≤ 60), and a patch only after an earlier overlay. Checked in
the browser on a 1024×576 clip:
- A hand-set move glides.
- "Players of board 1 move here" from a later frame matched 13 players, added
  1 and kept 1, and the board grew from 4 s to 7 s.
- The export matches the preview frame for frame. It sent 201 tile patches
  (35.5 MB) instead of 201 whole overlays (about 470 MB).

Limits, stated honestly:
- Matching is greedy (nearest pair first, same team, within 20 m), so two
  players crossing can swap tokens; drag to correct.
- The result is only as good as the later frame's calibration.
- A frame where more than half the tiles change is sent whole.

### Tests (M7 onwards)

Homography maths against known points; team split on fixed colour samples;
detections mapped to pitch metres; board inserts saved and reopened; old
documents unchanged; export of a board insert matches the preview; desktop and
narrow layouts; missing model pack reported clearly, never silently skipped.

## Roadmap after M5

Agreed order (2026-11-16). Each step gets its own plan before it starts.
Steps 1-4 need no AI model.

1. **Telestration M0-M5** (this plan), using whichever tracker M0 picks.
2. **Tactical board and inserts.** Freezes generalise to *inserts*: a segment
   in the exported clip held on a source frame (freeze), an image (for example
   a Tactical Lab export) or a blank pitch board. The board uses the same
   drawing tools; animated boards reuse keyframes (tokens move smoothly
   between keyframed positions). The Tactical Lab stays the data-driven view;
   the board is hand-drawn; they connect through "insert image".
3. **Coding on recorded footage.** A panel of buttons with hotkeys creating
   events at the playhead with lead-in and lead-out: instant codes, interval
   codes (press to start, press to stop), tags, and linked codes. Events feed
   the existing filter, clip and export pipeline and reuse period/kickoff
   alignment. Valuable for matches without a data feed (lower leagues, academy,
   training). Independent of the editor, so it can run in parallel.
4. **Pitch calibration, manual.** The analyst clicks four or more known pitch
   points; OpenCV computes the video-to-pitch mapping (homography). It follows
   pans and zooms by matching pitch features between frames; drift is
   corrected by re-clicking, with the same keyframe workflow as tracking.
   Unlocks unit shape (zones linked to seeded players), offside line, minimap,
   shapes flat on the pitch, distances in metres and player speed. Risk: fast
   pans, blur and frames with few pitch lines.
5. **Pitch calibration, automatic (model pack).** A pitch-keypoint model finds
   landmarks per frame so calibration does not drift; manual clicks stay as
   fallback and correction. Licence and training-data terms are the main
   hurdle.
6. **All-player tracking and teams (model pack).** Detector plus ByteTrack
   tracks every visible player in a clip; teams by shirt-colour clustering (no
   model); goalkeepers and referees tagged by the analyst. Makes team shape,
   offside line (last defender suggested) and minimap mostly automatic, and
   enables **"board from this frame"**: a frozen frame becomes a tactical board
   with every player's real position, ready for the analyst to move tokens.
   The ball stays out of scope.
7. **Segmentation (model pack).** A light model such as MobileSAM turns a
   player's box into an outline, as a background job before export. Enables
   drawings *under* players and the cut-out "move this player" tool. SAM 2 as
   an opt-in high-quality tracking mode if CPU speed allows.
8. **Live recording and coding.** Record a feed with the bundled ffmpeg
   (device input support to be checked on all three systems), recorded in
   short segments so the analyst can rewind while recording continues; same
   coding panel.
9. **Presentation builder.** Ordered annotated clips and boards exported as
   one video, extending the existing reel code (`analysis_reel`).
10. **Streaming to other devices.** Opt-in "share to bench" mode with a pairing
    code, read-only clips over the local network. Last because of
    local-network permission prompts and the AGENTS.md rule against exposing
    more than the app needs.

Out of scope even with models: automatic event spotting (overlaps the
AI-filtering question), real-time tracking of live feeds (needs a GPU), ball
tracking.

## Tests

- `segments.py`: span selection, keyframe precedence, merging, review flags,
  smoothing.
- `timeline.py`: source ↔ output mapping with zero, one and several freezes;
  animation progress at boundaries; a shared fixture checked against the JS
  implementation.
- Tracker: a generated synthetic video (a moving square on noise, with a brief
  occluder) so tracking tests are deterministic and need no real footage.
- Linked shapes: a zone linked to four synthetic tracks has the expected corners
  per frame; lost-track hold and review flag.
- API: input validation (no raw paths, bounded frame ranges, unknown clip),
  clip copy into project, save/reopen round trip, atomic write, cancellation
  mid-track and mid-export.
- Render: export a synthetic clip and check overlay pixels and text at known
  frames, including inside a freeze; output length equals clip plus freezes.
- E2E (Playwright): Annotate from each preview, draw, freeze, follow, correct,
  link a zone, save, reopen, export, cancel; desktop and narrow layouts; no
  console errors.
- CI on Windows, Linux and macOS: unit tests, build checks, and a packaged-app
  launch that imports OpenCV and Pillow and loads the font.

## Screenshots (user request, 2026-11-16)

The analyst can export the current frame, with its drawings, as a picture.

- **Screenshot** button and shortcut in the editor. It saves the frame on screen
  at the clip's full resolution (not the on-screen size), with every drawing in
  its state at that moment, including mid-animation and during a freeze.
- Built in the browser, so it adds no engine work: draw the video frame and the
  overlay onto one offscreen canvas at native size, encode PNG, and send it to
  the existing `POST /api/images/save` route (`save_image` in
  `clipmaker_api_server.py`), which already writes atomically to the user's
  folder and shows the "saved" pop-up. Its error text says "Chart pictures";
  generalise that wording to "Pictures".
- Optional JPEG for smaller files, chosen in the collapsible export options.
- A screenshot can also be annotated on its own: freeze the frame, draw, then
  take the screenshot. No separate image editor is needed.
- Tests: saved PNG has the clip's native width and height; overlay pixels match
  the preview at a known frame; a screenshot taken inside a freeze shows the
  frozen frame; oversize or empty uploads are rejected.

## Freeze behaviour (user decision, 2026-11-16)

- A freeze is a snapshot of one frame held for any duration the analyst sets.
  The length is adjustable after insertion (drag its edge on the timeline or
  type seconds); there is no fixed default beyond a sensible starting value.
- Audio is silent during a freeze. In export, the encoder inserts silence for
  the freeze length so audio stays in sync after it.
- Tests: a freeze of arbitrary length (including fractional seconds) produces
  exactly that much held picture and silence, and audio after the freeze lines
  up with the source.

## Still open

- Animation set: settled in M2 (2026-11-16) as R1 recommended: comes in with
  fade, draw-on, grow or slide in; goes out with fade; a pulse loop on rings,
  spotlights and zones; three easings (ease out, ease in and out, even).
- On-video text font: the user chose Segoe UI. It cannot be bundled (Microsoft
  licence), so Windows uses it and macOS/Linux fall back to Helvetica/Arial.
- Previously: animation set beyond draw-on, fade and grow kept as is. Before
  executing the plan, the user may run REA on Metrica Nexus (see R1) and add
  animations, tools or workflow ideas from that review, filtered by the
  light-and-fast principle.
