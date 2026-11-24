# M0 Tracking Spike – Results

Run 2026-11-16 on the user's laptop (Intel i7-10750H, 6 cores, CPU only).
Part of [TELESTRATION_PLAN.md](TELESTRATION_PLAN.md).

## Setup

- Clips: four VizorPlay clips from the same match, each 13 s, 1024x576,
  50 fps (650 frames): `01` close-up then goal, `04` and `05` wide play,
  `07` wide run with nearby players.
- One player seeded by hand on frame 0 of each clip.
- Trackers, all at native 576p (already near the planned 540p):
  - **MIL**: classical, in the standard OpenCV build, no model.
  - **CSRT**: classical, needs the OpenCV *contrib* build (confirmed: it is
    not in the standard build).
  - **ViT**: small learned tracker built into standard OpenCV, 0.7 MB model
    from `opencv/opencv_zoo` (`object_tracking_vittrack_2023sep.onnx`).
  - **Detector**: YOLOX-s (36 MB) through OpenCV DNN, person detections
    associated to the seeded player by motion and overlap.
  - NanoTrack was not tested: its model files come from a repository the
    user had not approved.
- Scoring by eye from one-per-second crops and full overlay videos; timing
  from the tracker update call only (decoding excluded).
- Spike code and outputs were kept outside the repo (scratchpad).

## Speed (tracker frames per second, higher is better)

| Clip | MIL | CSRT | ViT | Detector |
|---|---|---|---|---|
| 01 close-up | 11.5 | 14.0 | 67 | 3.1 |
| 04 wide | 19.4 | 38.3 | 159 | 2.9 |
| 05 wide | 21.0 | 28.5 | 167 | 3.1 |
| 07 wide | 19.8 | 42.6 | 127 | 3.3 |

Target was at least 25 fps. ViT passes everywhere with a large margin; CSRT
passes on wide shots but not close-ups; MIL fails; the detector is about 8x
too slow on this CPU through OpenCV 5's DNN engine (ONNX Runtime or a GPU
might help; untested).

## Did it stay on the player?

| Clip | What happened in the footage | Result |
|---|---|---|
| 04 | Player visible 0–4.6 s, then runs off the right edge | All four held him for the whole visible span. After he left, MIL, CSRT and the detector silently latched onto a red player at the edge; **only ViT flagged the loss** (at 5.2 s) |
| 05 | Player visible 0–2.6 s, then leaves the bottom of the frame as the camera pans | All four held him while visible. **ViT and CSRT flagged the loss at 2.9 s**; MIL and the detector did not |
| 07 | Continuous wide shot 0–7.9 s, then a replay cut | All four held the runner for the whole shot, past nearby players. After the cut all are wrong, as expected |
| 01 | Close-up 0–1.0 s, then a cut to the wide shot | All held until the cut. **ViT flagged the cut**; others carried on, on the wrong content |

## What this means

1. **Within a continuous shot, tracking is not the hard part.** Every
   tracker held the seeded player for every visible stretch in these clips.
2. **The real problems are cuts and players leaving the picture.** Every clip
   had one to three scene cuts (replays, angle changes), and in two of four
   the player left the frame. A tracker that does not notice this attaches the
   drawing to the wrong person. The plan's scene-cut detector found every cut
   in these clips; an out-of-frame rule (box reaching the edge and shrinking)
   is needed as well.
3. **ViT is the best fit.** Fastest by far, smallest (0.7 MB model, standard
   OpenCV build, so no contrib needed), and the only tracker that reported
   loss at the right moment in all three loss cases.
4. **CSRT is not needed.** It is slower, misses loss in some cases, and
   requires the contrib build.
5. **The detector is not worth it for following one player.** Too slow on CPU
   and it confidently followed the wrong player. It stays relevant for the
   later all-player features (roadmap step 6), where ONNX Runtime or a GPU
   would need testing.

## Not yet tested

- Re-acquiring the player after he comes back into the frame (by design the
  analyst re-seeds; the "first-use hint" covers this).
- Build size: both OpenCV builds unpack to about 135–140 MB here, but a clean
  standard-versus-contrib comparison inside a PyInstaller build was not done.
  To be measured in M1 packaging checks.
- Other matches, lighting, camera styles; the 50 fps clips may track more
  easily than 25 fps footage.

## Crossings (follow-up run, same day)

Footage: `Reims_Defensive_Transition_reel.mp4` (88 s, 50 fps, same match). A
detector pass found six moments where two players' boxes overlap after being
apart a second earlier, inside one continuous shot. Nine players were seeded
1.5 s before a crossing and tracked to 2 s after it (or the next cut):
red-versus-blue crossings, a tight duel over the ball (E4), a player starting
already overlapped (E2), runs into a group (E3) and a red passing a red (E5).

Two flags were tested on top of each tracker:

- the tracker's own "lost" signal (ViT and CSRT report one; MIL never does);
- a **shirt-colour check** with no model: the colour of the upper body inside
  the box, grass pixels masked out, compared with the seed; flagged when it
  stays different for a fifth of a second. A first version without grass
  masking fired on almost everything and was discarded.

Results for ViT, the proposed default (judged by eye from crops before,
during and after each crossing):

| Outcome over 9 crossings | ViT alone | ViT + shirt-colour check |
|---|---|---|
| Stayed on the player, no flag | 2 | 2 |
| Flagged for the analyst to check | 4 | 7 |
| **Silently switched to another player** | **1** (E0#0, blue to red) | **0** |

Of the 7 flags, at least 3 were real problems (a switch, a drift, a lost
player) and at least 1 was a false alarm (E4#1, a duel with an opponent inside
the box); the rest were borderline. CSRT and MIL alone never flagged anything
and switched or drifted silently in 2–3 (CSRT) and 4 (MIL) of the 9.

**What this means:** with ViT plus the shirt-colour check, a drawing did not
end up silently on the wrong player in any of the nine crossings, at the cost
of being asked to check most crossings. That is the right trade for an
analyst tool, and the UI should make the check cheap: at an amber frame,
one click for "still right" or a drag to fix. The reel had about 0.7 crossings
per 10 s, so even if every crossing needs a click, the "no more than 2
corrections per 10 s" target is met; dense penalty-box play will be busier.

**Limits:** nine crossings from one match with a strong red-versus-blue kit
contrast. Same-colour crossings (E5) are only caught by ViT's own signal, and
similar kits (white against light grey) will weaken the colour check. Re-test
on a second match with closer kits during M3.

## Decision (user, 2026-11-16): ViT approved

**ViT is the default tracker**, standard OpenCV build, with scene-cut
detection, an out-of-frame rule, ViT's own loss signal and the grass-masked
shirt-colour check driving review flags, plus a one-click "still right"
confirmation in the UI. MIL as a fallback if the ViT model file is missing.

ViT is a learned model, so it touches the proposed AI model policy, which says
the base app stays model-free. The user approved bundling the 0.7 MB model in
the base app as an exception. The model directory in `opencv/opencv_zoo` is
Apache 2.0; its training data is not stated in the README and should be
checked before release.
