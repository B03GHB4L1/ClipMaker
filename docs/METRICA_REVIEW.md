# Metrica Nexus Review (R1) – Triage for the VizorPlay Analyst Editor

Written 2026-11-16. Step R1 of [TELESTRATION_PLAN.md](TELESTRATION_PLAN.md).

## Method and limits

- Source: the REA analysis from 2026-10-12 in `Metrica Nexus/.rea-analysis/`
  (notes plus 1,385 source-map files recovered from the shipped app). No new
  decompiling, no running of Metrica, no network access. To keep token use low,
  only enum/model/factory files and method names were read, not whole modules.
- Static evidence only: an enum value shows a code path exists, not that every
  tool is reachable for every licence, nor exactly how it looks or feels.
- Used for **ideas and feature scope only**. No Metrica code, models, assets or
  file formats are copied into VizorPlay.
- Every recommendation is weighed against the plan's light-and-fast principle.

Key: **Adopt** = build it, as planned or nearly. **Adapt** = take the idea in a
smaller form. **Later** = worth it, but after the core editor works and is
measured. **Skip** = not worth its weight for VizorPlay.

## 1. How Metrica structures annotations

- Four top-level annotation kinds: video, audio, group, **pause** (their freeze).
- Every drawing has a start/end time on a timeline, a position, and a list of
  **track IDs**. Lines and polygons with several tracks connect those players;
  a line hides its free end point once it is attached to a track.
- **Parental groups** pass their tracks down to child drawings, so a group of
  shapes follows one player.
- Animations run on one of two clocks: **playback** time, or **accumulated**
  time that keeps running while the video is paused. That is how drawings
  animate during a pause. This matches our source-frames/output-time split, so
  the plan's design is confirmed rather than changed.

## 2. Drawing tools

| Metrica tool | What it is | Value | Cost | Verdict |
|---|---|---|---|---|
| Ring | Ellipse under a player's feet | High | Low | **Adopt** (planned) |
| Halo | Spotlight/glow on a player | High | Low | **Adopt** (planned spotlight) |
| Radar | Pulsing circles around a player | Medium | Low | **Adapt**: a "pulse" loop on the ring, not a separate tool |
| Line / arrow | Straight or curved, arrow types, dashes, thickness, fill pattern, closed shapes | High | Low | **Adopt** with curvature, dashed, arrowhead on/off, thickness. Skip fill patterns and 3D-on-pitch lines |
| Freehand | Free drawing | High | Low | **Adopt** (planned) |
| Text | Text with nine alignment anchors | High | Low | **Adopt** (planned) and add the nine-anchor alignment |
| Circle, polygon | Shapes and zones | High | Low | **Adopt** (planned zones); polygons linked to tracks = our dynamic zones |
| Track name | Label that follows a tracked player | High | Very low | **Adopt**: text linked to a track, no new code path |
| Future trail / trace | Line showing where a player goes next or has been | High | Low once tracking exists | **Adopt in M3**: drawn from the track's own positions |
| Magnifier | Zoom lens on an area | High | Low (crop + scale) | **Adopt**, can follow a player when linked to a track |
| Clip description | Caption card over the clip | Medium | Very low | **Adapt**: a text preset with a background, not a separate tool |
| Group / parental group | Move, show and track shapes together | Medium | Medium | **Adapt** later: simple grouping; our linked points already cover "follow a player" |
| Pause | Freeze with drawings | High | — | **Adopt** (planned freezes) |
| Chroma key | Keys out pitch colour so drawings appear *under* players | High polish | Medium; with a segmentation model, a background job before export | **Later**: roadmap step 7 (segmentation, model pack) |
| Dragger | Cut a player out and move them to another spot | Medium | Medium with a light segmentation model (was High) | **Later**: roadmap step 7 |
| Shape planar / 3D shapes / field 3D / field homography | Shapes lying flat on the pitch in perspective | High | Medium (manual calibration, no model) | **Later**: roadmap steps 4–5 |
| Team size, offside line, field radar (minimap) | Need players tracked plus pitch calibration | High | Unit shape: almost none. Offside/minimap: small after manual calibration. Fully automatic: model pack | **Later**: roadmap steps 4–6 |
| Sprite (sparkle effects) | Decorative animated sprites | Low | Medium | **Skip** |
| Slide, tactical board | Insert board slides into the timeline | High (user priority) | Low as editor inserts using the same drawing tools | **Later**: roadmap step 2; "board from this frame" in step 6 |
| Watermark | Logo on export | Low | Low | **Skip** |
| Coding pad | Event coding with buttons and hotkeys | High (user priority) | Moderate, no new dependencies | **Later**: roadmap step 3 (recorded footage), step 8 (live) |
| Capture, streaming, sharing | Recording a live feed; sending clips/data to other devices | High (user priority) | Recording: medium-high. Streaming: high (network, pairing, permissions) | **Later**: roadmap steps 8 and 10 |
| Live annotation | Drawing on a live feed in real time | Medium | High (needs low latency; real-time tracking needs a GPU) | **Skip** |

## 3. Animations

Metrica has:
- **In and out transitions** for all drawings: fade, slide (position),
  rotation, scale, sparkle sprite. Per-tool ones: ring width grows, halo fades,
  lines and freehand **draw on** along their path, shape strokes draw on.
- **Loops**: wobble in position, rotation or scale, and pulses for rings,
  halos and shapes.
- **31 easing curves**, 500 ms default duration.

Recommendation:

| Animation | Verdict |
|---|---|
| Fade in/out | **Adopt** (planned) |
| Draw-on for lines, arrows, freehand, zone outlines | **Adopt** (planned) |
| Grow (scale / ring width) | **Adopt** (planned) |
| Slide in | **Adopt**: cheap and useful for text and captions |
| Pulse loop for ring, spotlight, zone | **Adopt**: replaces the separate Radar tool |
| Easing | **Adapt**: three choices (linear, ease-out, ease-in-out), not 31 |
| Rotation, position/rotation wobble loops, sparkle | **Skip** |

This answers the plan's open animation question, subject to your approval.

## 4. Tracking workflow

Metrica's player tracking (`player-tracking.service`) offers: start/stop
tracking, manual versus automatic mode, **split track**, **rename track**,
team assignment, track names on screen, and tracking hints for first-time
users. Track edits deliberately skip undo to keep the tracking file in sync.

| Feature | Verdict |
|---|---|
| Start/stop tracking, manual seeding | **Adopt** (planned) |
| Split track | **Adapt**: our keyframes plus a "lost" state already split cleanly; add an explicit "end track here" |
| Rename track (player name) | **Adopt**: player label shown on the lane and usable by track-name text |
| Team assignment and colours | **Adapt**: optional team colour per track, used as the default drawing colour |
| Tracking excluded from undo | **Skip**: VizorPlay keeps keyframe edits undoable; re-tracking is just recomputed |
| First-use hint | **Adapt**: one short inline hint on Follow player, no tour system |
| Automatic tracking of all players | **Later**: roadmap step 6 (detector + ByteTrack, model pack); teams by shirt colour without a model |

## 5. Editing, shortcuts and presets

Metrica's shortcut list is large (~120 actions). The useful core for the
editor:

- Frame stepping: 1 frame, 1 s, 5 s, 15 s, both directions. Quarter-speed
  forward and reverse play. Speed up/down. Play/pause.
- Delete, cut, copy, paste, duplicate, undo, redo, select all.
- Bring to front, send to back.
- Add pause (freeze) at playhead.
- Group/ungroup.
- Save as preset.
- Zoom in/out/fit on the canvas.

| Feature | Verdict |
|---|---|
| Core shortcuts above | **Adopt**, shown in a compact help popover |
| Quarter-speed and reverse playback | **Adapt**: quarter-speed forward is cheap in `<video>`; reverse is unreliable in browsers, so use frame stepping instead |
| Canvas zoom | **Later** |
| Style presets (save a drawing's style, reuse it) | **Adopt** in a light form: named presets stored locally |
| Preset folders, import/export, favourites | **Skip** for now |
| Workspace layouts, pop-out windows, docking panels | **Skip**: VizorPlay keeps one compact editor page |

## 6. Export

Metrica exports through either a native FFmpeg encoder or the browser's
**WebCodecs** encoder. Options are H.264 or HEVC, five quality levels from
lowest to highest, and AAC audio. It also has a "container" export: a TAR with
JSON plus media, for moving projects between machines.

| Feature | Verdict |
|---|---|
| Quality presets on export | **Adopt**: reuse VizorPlay's existing encoder settings, expose three levels |
| HEVC | **Skip**: hardware-dependent, H.264 is enough |
| WebCodecs export | **Evaluate in M4**: rendering in the browser would guarantee the export matches the preview and avoid duplicating drawing code in Python. Needs a check that WebCodecs works in all three Tauri webviews (WebView2, macOS WebKit, WebKitGTK); fall back to the planned engine renderer where it does not |
| Container export (project + media bundle) | **Later**: VizorPlay projects are local; revisit if sharing between analysts is requested |

## 7. Performance techniques worth copying

- Tracking on video downscaled to 540 px at 25 fps (**already in the plan**).
- Separate rendering and encoding workers during export (**adopt**: keep export
  a background job with progress and cancel; consider a Web Worker if
  WebCodecs is used).
- Hardware encoding with a software fallback (**adopt** only if the existing
  encoder already supports it; do not add new dependencies for it).
- GPU-to-CPU fallback for models (**adopt if** ONNX Runtime is ever added for
  the model pack; OpenCV DNN on CPU is the starting point).

## 8. Changes this review suggests to the plan

If you approve the verdicts above:

1. **New tools**: magnifier (M1, fixed position; follows a player in M3),
   track-name labels (M3), future trail / trace (M3).
2. **Text**: nine-point alignment anchor.
3. **Lines/arrows**: curvature, dashed, arrowhead on/off.
4. **Animations**: fade, draw-on, grow, slide in; pulse loop; three easing
   choices. This closes the plan's open animation question.
5. **Tracking**: rename track (player label), optional team colour, explicit
   "end track here", one inline hint.
6. **Editing**: core shortcut set with a help popover, style presets,
   quarter-speed playback.
7. **Export**: evaluate WebCodecs browser rendering at the start of M4 before
   committing to the Python renderer.
8. **Later list**: grouping, canvas zoom, container export.
9. **Skipped**: sprites, watermark, live annotation, preset folders, HEVC.

## 9. Revisions after user input (2026-11-16)

The user is very interested in slides/tactical board, team shape/offside/
minimap, and live coding/streaming, and is slightly open to AI models. The
first version of this review skipped them because the heavy versions (Metrica's
~320 MB of models, live networking) fail the light-and-fast test. Each has a
lighter path, so they move from Skip to Later and onto the roadmap in
[TELESTRATION_PLAN.md](TELESTRATION_PLAN.md) ("Roadmap after M5"):

| Area | Light path | Model needed? | Roadmap step |
|---|---|---|---|
| Tactical board, slides | Editor *inserts*: freeze, image or blank pitch board with the same drawing tools; animated tokens via keyframes | No | 2 |
| Coding | Hotkey code panel on recorded footage feeding the existing clip pipeline | No | 3 |
| Pitch calibration | Manual 4-point click, followed between frames, corrected by keyframes | No | 4 |
| Unit/team shape, offside, minimap, flat shapes | Built on calibration plus seeded players | No (manual) / optional (automatic) | 4–6 |
| Automatic calibration | Pitch-keypoint model | Yes, model pack | 5 |
| All-player tracking, "board from this frame" | Detector + ByteTrack, teams by shirt colour | Yes, model pack | 6 |
| Drawings under players, cut-out move | Light segmentation model (MobileSAM-type) | Yes, model pack | 7 |
| Live recording and coding | Bundled ffmpeg, segmented recording | No | 8 |
| Presentation builder | Extend existing reel export | No | 9 |
| Streaming to other devices | Opt-in, pairing code, read-only | No | 10 |

Models only come in through the optional model pack under the plan's proposed
AI model policy (permissive licences for code, weights and data; one runtime;
clips not matches; output always correctable; pack under ~50 MB as a target).
The M0 spike is widened to compare classical tracking with a small detector
plus ByteTrack before any UI is built.

Still out of scope: automatic event spotting, real-time tracking of live
feeds, ball tracking, sprites, watermark.
