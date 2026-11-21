# M6 Board Spike – Results

Run 2026-11-17 on the user's laptop (Intel i7-10750H, 6 cores, CPU only,
OpenCV 4.10 DNN). Part of [TELESTRATION_PLAN.md](TELESTRATION_PLAN.md),
"Board from this frame (M6-M8)". Spike code and outputs were kept outside the
repo (session scratchpad).

**Verdict: go.** YOLOX-Nano (3.7 MB) on six tiles finds 93% of the players on
wide shots in under half a second, shirt colour puts about 94% of them on the
right team, and the whole board takes well under the 2 s target. The
homography step works in principle, but is the weakest link: its accuracy
depends on the analyst clicking points spread across the frame, so M7 must show
the fitted pitch lines on the video for checking (see below).

## Setup

- 20 frames from 16 clips of one match (Reims vs Strasbourg, 1024x576,
  50 fps): the 11 pass clips once each, the 4 shot clips twice, one reel.
  Three are close-ups (a throw-in, a goal celebration, a goalkeeper) with no
  pitch lines to calibrate from; they are left out of the scores below because
  no board can be made from them. 17 wide frames remain.
- Detectors, all YOLOX (Megvii, Apache 2.0), through OpenCV DNN:
  - **Nano**: 3.7 MB, 416 px input (downloaded from the official release
    0.1.1rc0, sha256 `c789161e…`).
  - **Tiny**: 20.2 MB, 416 px input (same release, sha256 `427cc366…`).
  - **S**: 36 MB, 640 px input (from the M0 spike).
- Each run on the whole frame, on 2 tiles (side by side) and on 6 tiles
  (3 x 2), 15% overlap, merged with non-maximum suppression. Person score
  above 0.3. Boxes are kept only if the feet stand on grass (a strip under the
  box is mostly green), which removes most spectators.
- Reference set: every box any run found, duplicates merged, then checked by
  eye: 13 boxes were not players or officials (stewards, photographers by the
  boards, a ball boy, a camera operator, a shadow) and 3 players were found by
  no run. 289 people on the pitch in total, referees included.

## Finding the players

| Detector | Mode | Found | Extra boxes (17 frames) | Seconds per frame |
|---|---|---|---|---|
| Nano | whole | 64% | 2 | 0.10 |
| Nano | 2 tiles | 88% | 3 | 0.19 |
| **Nano** | **6 tiles** | **93%** | **5** | **0.47** |
| Tiny | whole | 65% | 2 | 0.13 |
| Tiny | 2 tiles | 91% | 8 | 0.25 |
| Tiny | 6 tiles | 96% | 12 | 0.76 |
| S | whole | 75% | 4 | 0.48 |
| S | 2 tiles | 96% | 9 | 0.77 |
| S | 6 tiles | 96% | 7 | 2.28 |

- Tiling is what matters: players are 20-60 px tall in a 1024x576 frame, and
  the whole frame squeezed into 416 px makes them too small for any of the
  three. The model size matters much less once tiled.
- Nano on 6 tiles is the best trade: 3% fewer players than the 10x larger S
  model, at a fifth of its time.
- What is missed: players overlapping in a crowd (set pieces), players cut by
  the frame edge, and some very small far-side players.
- Extra boxes are mostly staff standing by the advertising boards at the far
  touchline, where the grass check still passes.

## Teams by shirt colour (no model)

- Colour taken from the torso band of each box (24-48% of its height), grass
  pixels removed, then only the *hue direction* (Lab a*, b* scaled to one
  length, pale pixels ignored). Two groups per frame; boxes far from both are
  "other" (referees, often goalkeepers).
- First try (plain colour) failed in bright sun: Strasbourg's blue shirts wash
  out to pale blue-white on the sunlit far side and joined the red team. Using
  the hue direction only, and the torso without the head, fixed most of it.
- Checked by eye on all 17 frames: about 16 wrong out of 289 (about 94% right).
  Typical errors: a pale far-side player in full sun, a referee put in a team,
  a red player in deep shadow marked "other". Referees in yellow come out as
  "other" in most frames.
- This match is an easy case (red against blue). Kits close in hue (for
  example white against light grey, or two dark kits) will do worse; the
  analyst's one-click team change stays essential.

## Video to pitch (homography)

Reading exact pitch-line points off the frames by eye was not precise enough
for a fair measurement, so this part was simulated, and checked against the
real frames for what is visible:

- **Landmarks visible** (by eye, 17 wide frames): 16 show at least four clean
  point landmarks (box corners, 6-yard box corners, goal-line and touchline
  intersections). The weak case is a midfield shot with only the halfway line
  and centre circle, which gives two or three clean points plus the circle.
- **Click error to metres** (a camera like the main broadcast camera, 30 m up
  and 45 m back, 1024x576 frame; 300 trials each):

| Scene | Points | Clicks off by | Median error | 90% under |
|---|---|---|---|---|
| Penalty area | 4 box corners | ~1 px | 0.35 m | 1.2 m |
| Penalty area | 4 box corners | ~2 px | 0.74 m | 2.4 m |
| Penalty area | 4 box corners | ~4 px | 1.5 m | 5.0 m |
| Centre circle | 4 | ~2 px | 1.5 m | 5.4 m |
| Centre circle | 6 (adds both touchlines) | ~2 px | 0.65 m | 2.1 m |

- Points close together (the four box corners) are accurate near the box but
  drift badly 30 m away; points spread across the frame (6, reaching both
  touchlines) halve the error. A token is about 1.5 m across, so 1-2 px
  clicks give a usable board.

## What M7 needs from this

1. **YOLOX-Nano, 6 tiles**, optional model pack (3.7 MB, checksum checked),
   feet-on-grass filter. Run the detector only when the analyst asks for a
   board; one frame costs about half a second.
2. **Calibration that can be checked.** After the clicks, draw the pitch lines
   back onto the video so a bad fit is obvious, and let the analyst drag any
   point to fix it. Offer a zoomed loupe while clicking (1-2 px accuracy).
   Ask for points spread across the frame; accept 4, prefer 6 or more.
3. **Centre-circle shots**: allow clicking points *on* the circle and on lines
   (not only corners), or ask for a point on each touchline.
4. **Teams**: hue-direction clustering per frame, "other" for outliers,
   one-click change of team, and a choice of which colour is home.
5. **Honest limits in the UI**: close-ups cannot make a board; off-screen
   players are missing; crowded set pieces may merge players.

## Not tested

- Other matches, kits, stadiums, broadcast styles, night games, rain.
- Higher source resolutions (1080p would make players bigger and detection
  easier, but six tiles would take about 1 s).
- Real clicks on real frames (the homography numbers are simulated).
- macOS and Linux speed; ONNX Runtime instead of OpenCV DNN.
- The training-data terms for the YOLOX weights (COCO) still need the same
  licence check as the other models in the AI model policy.
