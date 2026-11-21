# Coding, Live Feeds, Pitch Calibration, Tracking and Presentations

Plan drafted 2026-11-21 for roadmap steps 3-9 of `docs/TELESTRATION_PLAN.md`
("Roadmap after M5"), plus picture inserts deferred from M7. Step 10 (share to
bench) was dropped by the user on 2026-11-21. Each
milestone gets a short spike or design check before it starts, as M0 and M6 did.

The rules that bind every step:

- **Light and fast** (TELESTRATION_PLAN "Guiding principle"): nothing large in the
  base installer; heavy work runs as background jobs on clips, not full matches.
- **AGENTS.md model rules**: optional models are downloaded only when the user
  asks, from a fixed official address with a fixed checksum, run only on this
  computer, under Apache 2.0, MIT or BSD with training-data terms checked. The
  0.7 MB ViT tracker is the only bundled model.
- **No AI filtering**: models suggest positions and outlines; they never decide
  which events or clips matter. Automatic event spotting stays out of scope.
- **One shared frontend** for Windows, macOS and Linux; OS-specific capture
  sits behind platform adapters, and a missing capability is reported, never
  silently skipped.

## Order

| # | Step | Needs a model | Depends on |
|---|------|---------------|------------|
| C | Coding on recorded footage | No | - |
| L | Live recording and coding | No | C |
| P | Manual pitch calibration that follows the camera | No | Board calibration (M7) |
| A | Automatic pitch calibration | Yes (optional pack) | P |
| T | Tracking every player, with teams | Yes (detector already optional) | Board player finder (M7); P for pitch positions |
| O | Player outlines | Yes (optional pack) | Follow tracks (M1-M5) |
| B | Presentation builder | No | Annotated clips, boards, reels |
| I | Picture inserts | No | Board inserts (M7) |

I is small and independent; it can slot in at any point. C and P are independent and can run side by side. L follows C because live
coding is the same panel on a growing recording. B can start any time after C.

---

## C. Coding on recorded footage

### Goal

An analyst with only a match video (lower leagues, academy, women's football
without a feed, training) creates events by pressing keys while watching. Those
events then work exactly like scraped ones: filters, clips, reels, the Analyst
Room tabs that need only time and type, and export.

### How it works for the analyst

1. **Code window.** A new "Code" entry in the Intake workflow (Intake / Code /
   Filter / Analyst / Tactical), using the project's video and its kick-off
   markers. Big video, the code panel beside it, the coded list underneath.
2. **Code panel.** A grid of buttons, each with a hotkey and a colour. Three kinds:
   - **Instant code** ("Shot", "Corner", "Turnover"): one press makes one event
     at the playhead.
   - **Interval code** ("Possession A", "Pressing phase", "Build-up"): press to
     start, press again to stop. A running interval glows and shows its length.
     Intervals of one group can be exclusive (starting "Possession B" stops
     "Possession A").
   - **Tag** ("Left", "Successful", "Set piece", a player's name or number): a
     tag button labels the last event, or the next one if pressed first.
3. **Linked codes**: a button can carry tags automatically ("Shot" from the
   "Team A" side adds the team), and a code can start or stop another (a "Goal"
   stops the running possession).
4. **Lead-in and lead-out** per button (for example 6 s before, 4 s after a
   shot), so a clip is ready without trimming. Intervals use their own span
   plus the lead.
5. **Templates.** The panel is saved as a reusable template (JSON) shared across
   projects: "Match: two teams", "Training: drills", "Set pieces", "Keeper".
   Templates import and export as files so coaches can share them.
6. **Fixing codes.** Every event in the list can be nudged (±1 s, ±1 frame),
   retyped, retagged, deleted, with undo. Click an event to jump there.
7. **Players and teams.** Two team names and an optional squad list per project
   (shirt number and name). Number keys after a code assign a player
   ("Shot" then "9"). Optional; codes without a player stay valid.
8. **Pitch location (optional).** A small pitch beside the video: clicking it
   after a code sets x, y (and an end point for passes). Without it, events have
   no location and location-based filters say so instead of hiding the events.

### How coded events reach the existing pipeline

The filter, clip and export code reads an event CSV (`csv_path`) with match
clock columns (`minute`, `second`, `period`, `type`, `team`, `playerName`,
`outcomeType`, `x`, `y`, ...) and maps match clock to video time with the
period kick-off markers (`match_clock_to_video_time` in `clipmaker_core.py`).

- Coded events are **stored in video time** in `coded_events.json` in the
  project folder (atomic writes, as every project file), so nudging and
  re-timing kick-off never corrupts them.
- On every save, VizorPlay **writes a derived event CSV** from them in the
  scraped format, converting video time to match clock with the same kick-off
  markers (the inverse of `match_clock_to_video_time`). Intervals become one row
  with a `duration` column plus `end_minute`/`end_second`.
- A project's event source is then `scraped`, `coded`, or `both`. "Both" merges
  coded rows into the scraped table with a `source` column, so an analyst can
  add their own codes (pressing triggers, rest defence) on top of a data feed.
- Lead-in and lead-out ride along as per-row `before`/`after` columns that the
  clip cutter uses instead of the global buffer when present.

So Filter, clips, reels and export need no new code path, only the new columns.
The Analyst Room tabs that need locations work for coded matches only where
locations were clicked; the rest show their usual "no data" message.

### Engine and API

- `app/coding/` with `store.py` (validated read/write of `coded_events.json` and
  templates), `to_events.py` (video time to match-clock rows, CSV writer) and
  tests.
- `POST /api/projects/<id>/codes` (add/update/delete in batches, validated: known
  code ids, times inside the video, at most N events), `GET` for the list,
  `GET/POST /api/code-templates`. No filesystem paths from the browser.

### Milestones

- **C1** Code window, instant codes, hotkeys, list with jump and delete, saved;
  derived CSV; Filter and export work on a coded-only project. Done 2026-11-21.
- **C2** Interval codes, exclusive groups, lead-in/out, nudging, undo. Done 2026-11-21. Clips of coded
  rows are cut at their exact video time (`clipmaker_core.coded_video_time`), so
  shootout codes do not depend on the first-kick marker; a frame nudge uses the
  video's measured frame length (1/25 s until it has played).
- **C3** Tags, linked codes, templates (save, import, export), squad list.
- **C4** Pitch location clicks; "both" source merging with scraped data.

### Tests

Round trip video time to match clock to video time across halves and extra
time; derived CSV matches the scraped schema; a coded-only project filters,
cuts and exports in the browser smoke test; hotkeys never fire while typing in
a field; templates reject unknown fields.

---

## L. Live recording and live coding

### Goal

Code a match while it happens, from a camera or a stream, and have clips ready
at half time. The roadmap already had this as step 8; it moves up because it
shares the code panel with C.

### Sources

VizorPlay records with its bundled FFmpeg. Sources, each behind a platform
adapter and checked on all three systems in a spike:

1. **Capture device**: a USB camera or HDMI capture card (DirectShow on
   Windows, AVFoundation on macOS, V4L2 on Linux).
2. **Network stream** the user supplies: an RTMP/SRT/RTSP/HLS address from a
   club camera, a phone app or OBS. VizorPlay can also listen for an RTMP or SRT
   push on localhost only, so OBS or a phone on the same machine can send to it.
3. **Screen or window capture** as a fallback for footage only visible in a
   player window. Capturing broadcasts is the user's responsibility; the UI says
   so once, plainly.

### How it works

- **Segmented recording**: FFmpeg writes short segments (for example 6 s, HLS
  style, no re-encode when the source codec allows) plus a growing playlist, so
  the editor can play, pause and rewind behind the live edge while recording
  continues, and a crash loses at most one segment.
- **Kick-off at a key**: "Kick-off" and "Half time" buttons set the period
  markers live, so match clock is right from the first code.
- **Live coding**: the same code panel; codes stamp the recording clock. A
  "live edge" button jumps back to now.
- **Clips during the match**: any coded event can be cut and played as soon as
  its lead-out has been recorded; a reel of "first half" is ready at half time.
- **After the match**: segments are joined into one MP4 (stream copy) and the
  project becomes an ordinary recorded project.
- **Limits stated in the UI**: disk space shown and warned at a threshold; if
  the source drops, recording keeps the gap and resumes, and the gap is marked.

### Milestones

- **L0 spike**: device listing and 30-minute recording on each OS (CI cannot
  test devices, so a manual checklist plus a CI test with a generated stream).
- **L1** Network and localhost-push recording, segmented, play behind the live
  edge, join at the end.
- **L2** Live coding, live kick-off markers, cutting clips while recording.
- **L3** Capture devices and screen capture per OS.

---

## P. Manual pitch calibration that follows the camera

### Goal

Know where every pixel is on the pitch through a clip, so drawings can lie flat
on the grass and VizorPlay can show offside lines, a minimap, distances in
metres and player speed.

### How it works

- The analyst clicks four or more known pitch points on one frame (the same
  landmark picker boards use since M7, `ui/annotate/pitch.js`). OpenCV computes
  the frame's homography.
- **Following the camera**: from that keyframe, VizorPlay tracks pitch features
  (line intersections, ORB/feature matches on the grass region) frame to frame,
  forward and backward, and updates the homography. It runs as a background job
  like follow tracking, with the same confidence states.
- **Correction is the tracking workflow**: low-confidence frames (fast pans,
  blur, few lines, replays and close-ups) are flagged; the analyst re-clicks on
  one of them, which becomes a new keyframe; segments between keyframes blend.
- **Cuts and replays**: a scene cut stops the track; frames without enough pitch
  are marked "no pitch" rather than guessed.

### What it unlocks (each a small tool once P exists)

- Shapes drawn **flat on the pitch** (zones, arrows, circles in perspective).
- **Offside line**: a line across the pitch at a chosen player's depth.
- **Minimap**: the followed players' positions on a small 2D pitch.
- **Distances and speed**: between two followed players or along one player's
  track, in metres and km/h, smoothed.
- Positions of followed players exported to the event table for coded matches.

### Milestones

- **P1** Calibrate one frame in the editor and show the projected pitch lines
  to check it; shapes flat on the pitch at that frame.
- **P2** Camera following, confidence, re-click correction, saved per clip.
- **P3** Offside line, minimap, distances and speed.

### Risks

Wide-angle and fisheye lenses (add a simple lens distortion term if the spike
shows it is needed), fast pans, low-angle cameras with few lines.

---

## A. Automatic pitch calibration (optional model pack)

- A pitch-keypoint model finds landmarks on every frame, so calibration does not
  drift and needs no clicks on standard broadcast angles. Manual clicks (P) stay
  as the fallback and the correction.
- **Licence first**: the step starts with a search for a keypoint or
  line-segmentation model whose code, weights and training data allow Apache
  2.0 / MIT / BSD use. If none qualifies, this step waits; P covers the need.
- Measured against P on the test clips: clicks saved, accuracy in metres, speed
  per frame on CPU, download size. Rejected if it does not clearly beat P.

---

## T. Tracking every player, with teams

### Goal

Every visible player tracked through a clip, split into teams, so team shape,
the offside line's last defender and the minimap are mostly automatic, and
"board from this frame" works on any frame of the clip.

### How it works

- **Detection**: the YOLOX-Nano player finder boards already use (optional
  download), run every frame or every second frame on the clip, as a background
  job.
- **Association**: ByteTrack-style matching (motion plus box overlap, no
  appearance model) written in NumPy, so no new dependency; the ViT follow
  tracker can bridge a player through short occlusions when asked.
- **Teams**: shirt-colour clustering, as boards do; goalkeepers and referees are
  tagged by the analyst with one click and kept.
- **Pitch positions** when P is calibrated: tracks become positions in metres.
- **Correction**: merge two tracks, split one, delete a false one; the analyst's
  fixes win over the model, as with follow tracks.
- Ball tracking stays out of scope.

### Milestones

- **T0** Done 2026-11-21: the COCO training-data terms pass (annotations CC BY
  4.0, no restriction on trained models; see `docs/M6_BOARD_SPIKE.md`). Before
  T1 ships, add the YOLOX and COCO credits to the app's licence notices.
- **T1** All-player tracks on a clip, drawn as rings, with team colours.
- **T2** Corrections; "board from any frame"; tracks to pitch positions with P.
- **T3** Team shape (lines joining a unit), auto last-defender offside line.

---

## O. Player outlines (optional model pack)

- A light segmentation model (MobileSAM-class) turns a followed player's box
  into an outline, as a background job before export, on the frames that need
  it only.
- Enables **drawings under players** (a zone or arrow passes behind the player
  instead of over them) and the **"move this player"** cut-out tool on freezes
  (lift a player and place them where they should have been).
- Licence and size check first; measured for CPU speed per frame. SAM 2 as an
  opt-in high-quality mode only if CPU speed allows.
- **O1** Outlines for followed players on freezes; drawings under players.
  **O2** Through moving segments; "move this player".

---

## B. Presentation builder

### Goal

One video for a team meeting: an ordered list of annotated clips, boards, coded
clips and title cards, exported in one go.

### How it works

- A **Presentation** page per project (and across projects): add items from
  annotated clips, coded events, Filter clip sets, Tactical Lab images and
  boards; drag to reorder; per item a title card (text over blank pitch or
  black) and optional pause.
- Export reuses the reel code (`analysis_reel`) and the annotation export, with
  the VizorPlay footer credit optional on title cards.
- Saved as part of the project; reopen and re-export after edits.
- **B1** Ordered list of annotated clips and Filter clips, one export.
  **B2** Title cards, images and boards as items, cross-project presentations.

---

---

## I. Picture inserts

Deferred from M7. A picture (a Tactical Lab or Analyst Room chart, a PNG the
analyst has, a line-up graphic) shown for a few seconds inside an annotated
clip, with the same drawing tools on top.

### How it works for the analyst

- **Insert picture** beside "Insert freeze" and "Board from this frame" in the
  editor. It adds an insert of 4 s (adjustable, like a freeze) at the playhead.
- Picture sources:
  1. **From a chart**: every chart's export controls get "Send to clip",
     which saves the picture (with the VizorPlay credit strip) to the
     project's picture library, and the editor's picker lists it first.
  2. **From a file**: a file picker (PNG, JPEG, WebP), validated and copied
     into the project; the browser never sends a path.
- **Fit**: contain (whole picture, background colour around it) or fill (crop
  to the frame), and a background colour (paper, pitch green, black).
- Drawings, text, spotlights and animations work on the insert as on a freeze;
  audio is silent, as for freezes.

### Engine

- The freeze `background` gains `{"kind": "picture", "id", "fit", "colour"}`
  (the shape M7 left room for); `annotations.py` validates it, and old projects
  open unchanged.
- Pictures are stored in `projects/<id>/pictures/<id>.png`, re-encoded on
  upload (so the file is always a clean PNG), at most 4096 px a side and 20 MB,
  written atomically. `POST /api/projects/<id>/pictures` (raw body, like
  `/api/images/save`), `GET` to list, `DELETE` refuses while an insert uses it.
- Export draws the picture as the insert's background frame through the same
  path as board backgrounds.

### Milestones and tests

- **I1** Upload route, picture library, insert with contain/fill, export.
- **I2** "Send to clip" from chart exports, in both themes.
- Tests: oversize and non-image uploads refused; a project with a picture
  insert saves, reopens and exports with the picture's pixels in the right
  frames; deleting a picture in use is refused.

---

## Still open (for the user)

1. **C first or C and P together?** They are independent; P is mostly engine
   work and C mostly UI.
2. **Default code templates**: which buttons should a new match template start
   with (for example Shot, Goal, Corner, Free kick, Turnover, Press win,
   Possession A/B, Build-up)?
3. **Live sources to prioritise**: a phone or club camera stream (RTMP/SRT) is
   the most common and easiest; capture cards and screen capture follow.
4. **Coded and scraped together**: should coded events on a scraped match show
   in the Analyst Room tabs, or only in Filter and clips?
