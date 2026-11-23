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

**Decided 2026-11-23, to ship soon:** C, L and P (P1 to P3) are done. Next are I, then B. T (tracking every player, with
teams), A and O are left for a future update,
along with one more (asked 2026-11-23): exporting the positions of followed players to the event table for coded matches.
Asked 2026-11-23, after I and B (a small P3c): a speed-over-time chart for a followed player and its export (done 2026-11-23: in the Follow panel, with Save chart and Send to clip); and a Measure that can end on followed players, so its distance updates as they move (done 2026-11-23: an end dropped on a followed player's feet follows them).

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
- **C3** Tags, linked codes, templates (save, import, export), squad list. Done 2026-11-21.
  Panels live in `app/coding/templates.py` (built in: Match, Set pieces, Training,
  Goalkeeper; the analyst's own in `code-templates/`). A project keeps its own copy
  and refuses a panel that lacks codes it has used. A tag can set the outcome or one
  of Filter's qualifier columns; each qualifier still applies to its own event types
  (Big chances to shots, Headers to passes). The in-app editor changes names, keys,
  colours, codes and tags; links between codes came with C5.
- **C4** Pitch location clicks; "both" source merging with scraped data. Done 2026-11-22.
  A click on the Code screen's pitch sets x, y in the feeds' scale (the event's team
  attacking right); a drag adds endX, endY. Coded rows carry depth_zone and pitch_zone,
  so Filter's lane and depth filters work on them, and Filter says how many coded events
  have no location. With a scraped or imported table, coded rows join a copy of it
  (`match-data/merged_events.csv`, `source` "feed" or "coded"); the feed file is never
  changed, deleting every code goes back to it, and a new scrape or import is merged
  again. The Analyst Room, Tactical Lab and the score read the feed alone, so a coded
  Goal is not counted twice.
- **C5** Code-link editor, before L1, so the panels people record live with carry their
  own links. Done 2026-11-22. In the panel editor each code's Links row sets which interval
  codes it starts (for the same or the other team), which it stops, and which of the
  panel's tags it adds (`ui/code/links.js`; at most 4 starts, 4 stops, 10 tags). Links to
  a removed code or tag go with it. `app/coding/templates.py` refuses links to codes or
  tags the panel does not have, starts or stops of instant codes or of the code itself,
  and entries that are not names.

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
- C5 (the code-link editor) comes first, so live panels can carry their own links.
- **L1** Network and localhost-push recording, segmented, play behind the live
  edge, join at the end. *Done 2026-11-22.* The network half of the L0 spike was
  done here: the bundled Windows FFmpeg (7.1) reads RTMP, SRT, RTSP and HLS and listens
  for an RTMP or SRT push on 127.0.0.1; a CI test pushes a generated stream over RTMP.
  Device listing and the 30-minute run per OS move to L3.
  - `app/live/recorder.py`: 2-second fMP4 segments per connection ("part"); H.264 is
    copied, anything else is encoded to H.264; audio becomes AAC. A drop starts a new
    part when the source returns and notes the gap (`live_gaps` on the project: where
    in the joined video, and how many seconds were lost). Below 2 GB free the page
    warns; below 300 MB the recording stops. Sources are checked against FFmpeg's own
    protocol list, and a missing one is reported.
  - Stop joins the parts without re-encoding into Videos/VizorPlay/Recordings, and the
    file becomes the project's video. Segments left by a crash or by closing the app show
    as an unfinished recording that can still be saved. One recording at a time;
    a project that already has a video cannot record over it.
  - Code screen: a record form on a project without a video, and a live bar (time,
    free space, breaks, Live, Stop and save). Playback uses Media Source Extensions
    and keeps only about two minutes around the playhead in memory. Coding is locked
    until the recording is saved (that is L2).
  - The page reads only `init.mp4` and `seg_NNNNN.m4s` by fixed names; addresses
    must be rtmp(s), srt, rtsp(s) or http(s), never files.
- **L2** Live coding, live kick-off markers, cutting clips while recording.
  *Done 2026-11-22.*
  - The code panel works while it records. Codes stamp the playhead in recording time,
    which is the joined video's time, so nothing moves when the recording is saved;
    the coded table is rewritten against the file then.
  - "Kick-off" in the live bar marks the next period without a marker (1st half,
    2nd half, extra time, penalties) at the playhead, in whole seconds, after the
    earlier one. Intake corrects them as before. The model stores kick-offs only,
    so there is no separate half-time button.
  - Each finished code gets a "save clip" button while it records: the code's lead-in
    and lead-out, re-encoded from the segments so it starts on the exact frame, saved
    to the export folder like other clips. Up to 5 minutes; a clip whose end is not
    recorded yet says how many seconds to wait; one that runs into a break in the
    stream ends where the break starts. Reels (a whole half) stay on Filter once
    the recording is saved.
  - The video stage stays black in the dark theme (it showed grey before a video loaded).
- **L3** Capture devices and screen capture per OS. *Done 2026-11-22.*
  - `app/live/devices.py` is the platform adapter. Windows: DirectShow for cameras,
    capture cards and microphones, GDI for the whole desktop. macOS: AVFoundation for
    all three (each screen is listed). Linux: Video4Linux2 cameras, the default
    PulseAudio or ALSA microphone, X11 for the screen; a Wayland session is told it
    cannot record the screen. Whatever this FFmpeg lacks is stated on the form.
  - The page sees device names only. A recording names one, and the name is looked up
    again in a fresh listing when it starts, so nothing else reaches FFmpeg.
  - On Windows the camera's largest mode up to 1080p that keeps 25 frames a second is
    chosen (the test laptop's camera defaults to 640x360 but gives MJPEG 1280x720 at 30;
    its raw 720p only manages 8). Cameras and screens are always encoded to H.264
    (veryfast, zerolatency); screens are scaled to 1920 wide at most.
  - Code screen: "A camera or capture card" and "This computer's screen" on the record
    form, with Camera or Screen, Sound (or no sound) and "Look again".
  - macOS: `src-tauri/Info.plist` adds the camera and microphone usage strings, which
    macOS needs before it shows its permission prompt; the Mac app check asserts them.
    Screen recording is allowed under Privacy & Security, Screen Recording.
  - Checked on Windows 11 (the laptop camera with its microphone, and the desktop):
    record, play behind the live edge, stop and save. CI records the screen on Windows
    only (the Linux job has no X display, and macOS needs a permission a runner cannot
    give). The bundled FFmpeg has the inputs on all three: Windows dshow and gdigrab;
    macOS avfoundation; Linux v4l2, x11grab and ALSA (no PulseAudio, so the default ALSA
    microphone). Not checked by hand: macOS and Linux devices, a capture card, a
    30-minute run on each system.

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
  to check it; shapes flat on the pitch at that frame. *Done 2026-11-22.*
  - "Mark the pitch" (Add at this frame) opens the board's calibration panel in a
    pitch mode: the same marks, loupe, drag and fit grading in metres, with "Save
    pitch" and "Remove pitch". Reopened on the marked frame, it shows the saved marks.
  - The clip's document keeps `pitch: {keys: [{frame, pairs}]}`. The frame is the clip's
    recorded frame, not its place after cutting, so splitting or trimming keeps it.
    One key for now; P2 adds a key per camera move. The engine checks the frame, 4 to
    40 marks, their names and positions; marks off the landmark list are ignored by
    the fit.
  - "Pitch lines" and "Go to frame N" under the button: the fitted lines are drawn on
    the marked frame, as during marking.
  - "Flat on the pitch" in a ring's or arrow's settings (offered once the clip has a
    pitch). A flat ring is a true circle on the grass, its size read out in metres; a
    flat arrow's head lies on the grass, smaller further away, with the arrow's length
    in metres. Drawn by `ui/annotate/flat.js` through the calibration, in the editor,
    screenshots and exports alike. A ring on a followed player stays an ordinary ring.
  - Until P2 the calibration is the one frame's: on other frames flat drawings keep
    their shape where they were drawn, like every drawing, rather than following the
    pitch as the camera moves.
  - Checked in the browser with marks from a known camera (fit 0.0 m), a flat ring and
    arrow, saved and reopened, and an export whose frames show them as on screen.
    Not yet tried: marking a real frame by hand on several matches.
- **P2** Camera following, confidence, re-click correction, saved per clip.
  *Done 2026-11-23.*
  - "Follow camera" under the pitch button runs `app/telestration/camera.py` as an
    editor job (progress, Stop). It measures each frame against a reference frame
    (corners and optical flow, a RANSAC similarity, a full homography only when the
    picture clearly needs one), so small errors do not pile up frame after frame. A
    median filter removes single-frame jolts. A scene cut starts a new stretch. Each
    frame keeps how sure the step is (share of corners that agree, fewer corners
    count for less). Up to 4,500 frames per clip.
  - The clip keeps `pitch: {keys: [...], camera: {from, rows, starts}}`. A key can be
    added on any frame (up to 50): "Mark the pitch" on another frame adds a key, on a
    marked frame it replaces it. "Remove marks" removes this frame's key; the last
    key takes the camera path with it.
  - Between two keys the pitch blends both, leaning on the nearer one, so it reaches
    each key without a jump. Frames reached only through a step under 0.15 sureness
    are "to check": their pitch lines are drawn amber and "Next to check" jumps to
    them, with a line saying what is wrong (doubtful, or no pitch after a cut). Marking
    the pitch on such a frame is the re-click correction.
  - Flat drawings keep the frame they were drawn on (`at`) and are placed through the
    pitch on every other frame, in the editor, screenshots and exports. Where the
    camera was followed but a frame has no pitch (after a cut), they are hidden.
    Without a followed camera they stay as drawn, as in P1.
  - Checked: generated pan, zoom and cut clips (under 2 px over 60 frames, also on a
    softer encode after Linux CI found a 9 px step there), and one
    real 29 s broadcast clip (1,450 frames in 24 s, cuts to close-ups found, a flat ring
    staying on the grass across the pan and hidden after the cut). With marks only on
    the far half, the near touchline was 20 to 40 px off on other frames.
    Not yet tried: several matches, long zooms, marks spread over the whole pitch.
- **Shape tool** (asked 2026-11-23): a Shape button under Draw (key G) opens a row of
  shapes beside it (below it on a phone): rectangle, ellipse, triangle, diamond,
  pentagon, hexagon and star. Drag to draw, Shift for equal sides; the shape can be
  changed later in its settings. Filled and patterned like a zone.
- **P3** Offside line, minimap, distances and speed. In two parts.
  - **P3a** Offside line and Measure. *Done 2026-11-23.* A "Pitch" group in the toolbar.
    - Offside (key O): click a spot, such as a defender's boot, and a line is drawn across
      the pitch at that spot's depth, touchline to touchline, a true line on the grass in
      perspective. Its settings say how far it is from each goal line.
    - Measure (key M): drag between two spots on the grass; the distance in metres is
      shown on a label at the middle of the grass between them (a far-side metre is
      smaller on screen, and the number accounts for it).
    - Both are always flat: they keep the frame they were placed on and stay on the same
      grass as the camera moves (as flat rings do), are hidden where a frame has no pitch,
      and appear in screenshots and exports. They need the pitch marked first, and say so.
      They are fixed to the grass: they do not follow a followed player, and go on the
      video, not on a board. Following a player with the offside line comes with T3.
    - Checked: node tests on generated cameras (line depth, metres, placement while
      panning, hit-testing) and engine validation; in the browser on the real clip
      (placing both, saving, following the pan, hidden after the cut, phone width, dark).
      Not yet tried: marking and measuring on other matches.
  - **P3b** Minimap and speed. *Done 2026-11-23.*
    - Speed: select a followed player's drawing and the Follow panel's "Speed on the pitch"
      says their speed on this frame in km/h, their top speed and the frame it was on, and
      the metres covered. It is read from their feet through each frame's own pitch
      (`ui/annotate/motion.js`), so a panning camera is not counted as running. Positions are
      smoothed with a straight-line fit over 0.3 s and speeds taken over 0.5 s, leaning
      forward or back at the ends of a track; anything over 45 km/h is a tracking slip and
      is left out. It needs the pitch marked and the camera followed.
    - Minimap (key N, Pitch group): click where its top-left corner goes. A small pitch,
      far side up as in the picture, with a dot for each followed player on the frame. Its
      colours and size are settings. It stays where it is put on the picture (no player
      link, video only, not a board), and is in screenshots and exports.
    - Checked: node tests (steady running, jitter, a panning camera, gaps, a tracking slip,
      the map's box and hit-testing) and the engine's rules; in the browser on the real
      clip, with one followed player (a walking pace of about 6 km/h, 6 m in 3.6 s) and an
      export whose frames show the map's dot on the near side where the player is, as the
      pitch numbers say (15 m right of centre, 30 to 32 m from the far touchline).
      Not yet tried: several followed players on the map, other matches, a long run.
      The map shows nothing for frames with no pitch (after a cut). Team colours on the dots
      come with T (tracking every player, with teams).

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

*Deferred to a future update (2026-11-23); nothing below is started beyond T0.*

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

- **I1** (done 2026-11-23) Upload route, picture library, insert with contain/fill, export. Pictures are re-encoded to clean PNGs
  (at most 4096 px a side, 20 MB, 200 per project) in `projects/<id>/pictures/`; an insert is a freeze whose background is a
  picture; deleting a picture an insert shows is refused.
- **I2** (done 2026-11-23) "Send to clip" from the export of any chart: a button beside PNG in the shared chart component
  (Analyst Room event charts) and in the Plotly toolbar (Comparison, Tactical Lab). It sends the same branded picture to the
  active project's pictures. The Filter page has no chart export of its own.
- Tests: oversize and non-image uploads refused; a project with a picture
  insert saves, reopens and exports with the picture's pixels in the right
  frames; deleting a picture in use is refused.

---

## T2. Editor-style timeline (replaces the presentation builder, B)

B is dropped: a presentation builder is a clunky video-editor timeline, so the
Annotate timeline itself becomes the editor.

**Stage 1 (done): one clip.** Ruler with labels and ticks spaced on their own
(frame-level when zoomed far in), zoom 1-60x (buttons, Ctrl+wheel, around the
playhead), one red playhead through every track, sticky track headers, named
blocks (video part, inserts, boards, drawings), click or drag the ruler to seek,
and snapping (10 px to the playhead, clip ends and other blocks' edges; Alt
places freely) with a dashed snap line. Ideas for the ruler and snapping come
from OpenCut (MIT); nothing is copied, only reimplemented.

**Stage 2: several clips on one sequence (scoped 2026-11-23).**

What exists: a project already has *sessions* (`sessions.json`, an ordered list of
clip ids), each clip has its own annotations (parts, freezes, boards, picture
inserts, drawings), and export renders one clip at a time with overlays drawn by
the page (`run_export`). So a sequence is a session with order, plus a way to
play and export it as one video. No new clip format is needed.

Build order, each step shippable on its own:

- **S1 Sequence strip.** A track above the clip's lanes showing every clip of the
  session as a named block sized by its output length (parts and freezes
  included). Click a block to open that clip, drag to reorder (saved in
  `sessions.json`), Add clip / Add picture. Same ruler, zoom and snapping.
- **S2 Sequence export.** One Export button renders each clip with the existing
  per-clip path into a temporary file, then joins them with ffmpeg. Clips of a
  different size or frame rate are scaled and padded to the first clip's. Audio
  is kept per clip (silence where a clip has none). One progress bar across all
  clips; cancel stops the current clip and removes everything written.
- **S3 Stand-alone pictures and title cards.** A sequence entry that is only a
  picture (from the existing picture store) or a text card, with a duration;
  rendered as a still segment.
- **S4 Play across clips.** The preview keeps one video element, so playing the
  sequence swaps clips at each boundary (preload the next). Needed for a true
  one-timeline feel; hardest, so last. Until then the strip is for arranging
  and exporting, and playback is per clip.

Decisions: cuts only (no fades or transitions) in the first version; trimming
stays per clip (parts) rather than trimming blocks on the strip; sequence
export goes to the project's export folder like a single clip.

Tests: ordering and persistence (pytest), join plan for mixed sizes/fps and
audio gaps (pytest, tiny ffmpeg clips), strip markup and reorder (test_ui and
browser smoke), cancel leaves no files.

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
