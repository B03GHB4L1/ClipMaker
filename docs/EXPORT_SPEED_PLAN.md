# Plan: faster cutting and export without losing quality

Status: steps 1-5 implemented 11 November 2026 (results below); CI pending.

## Baseline (11 November 2026)

Windows 11, 12 threads, NVIDIA GeForce GTX 1660 Ti; frozen backend; a real
1080p 50 fps H.264 broadcast (8.4 Mbit/s, keyframe every 1-2 s).
`tests/workflow_timing.py` drives the real API.

| Step | Time |
|---|---|
| Backend cold start | 0.53 s |
| Intake page usable | 2.6 s |
| Live Scoresway scrape | 4-6 s (one run 55 s: provider-side delay, not repeated) |
| Filter options / clip windows | 0.03-0.14 s |
| Render one 13 s preview | 7.9 s |
| Export 20 clips as a reel (1,522 s of video) | 872 s, 1.75x real time |
| Same, as individual clips (4 at once) | 1,078 s |

Filtering, scraping and startup are not the problem. Export and preview are:
every clip is re-encoded with libx264 (`veryfast`, CRF 20), which runs at the
encoder's own speed (1.8x real time here). Running four x264 encoders at once
is slower, not faster, because each already uses every core.

## Encoder measurements (same 60 s segment)

Quality is VMAF (0-100, higher is better; 95+ is visually transparent for
most viewers) and SSIM against a lossless copy of the source segment.

| Encoder | Speed | Bitrate | VMAF | SSIM |
|---|---|---|---|---|
| x264 veryfast CRF 20 (current) | 1.8x | 8.3 Mbit/s | 96.1 | 0.985 |
| NVENC p5 CQ 27, GPU decode | 5.6x | 10.7 Mbit/s | 97.8 | 0.986 |
| NVENC p5 CQ 25, GPU decode | 5.5x | 13.7 Mbit/s | 98.7 | 0.989 |
| NVENC p7 CQ 27, GPU decode | 3.0x | 10.9 Mbit/s | 98.0 | 0.986 |
| Stream copy (no re-encode) | 24x | source | lossless, but starts at the previous keyframe | |

## Plan

1. **Hardware encoding when available, x264 otherwise.** Detect a working
   hardware H.264 encoder once per FFmpeg binary with a tiny test encode
   (NVIDIA NVENC first; Intel Quick Sync, AMD AMF and Apple VideoToolbox only
   after their quality mapping is measured on real hardware). Map the existing
   quality setting (CRF 16-30) to NVENC CQ = CRF + 7, which measured equal or
   better than x264 at CRF 20. Decode on the GPU when using NVENC.
2. **Never mix encoders inside one reel.** Parts of a reel are joined by
   stream copy, so one job uses one encoder. If a hardware encode fails, log
   why, switch the job to x264 and re-cut its parts. Never silent: the export
   log names the encoder used.
3. **A setting to opt out.** Export settings get "Encoder: Automatic (use the
   graphics card when available) / Software (x264)". Saved with the project
   like the other export settings.
4. **Previews use the same encoder choice,** so a 13 s preview should take
   about 2-3 s instead of about 8 s.
5. **Parallelism by measurement.** Individual clips currently cut 4 at once,
   which is slower with x264. Pick the worker count per encoder from the
   short-clip benchmark below.

Later, separately: "smart cut" (re-encode only up to the next keyframe, copy
the rest) could approach stream-copy speed with source quality, but joining
re-encoded and copied H.264 needs matching stream parameters and careful
testing across players.

## Verification

- Unit: encoder detection and fallback order, CRF to CQ mapping, one encoder
  per job, fallback re-cuts all parts, the setting is validated and saved.
- Media: real cut with each available encoder: duration, start time (pixel
  check as in the existing media tests), audio present, decodes cleanly.
- Quality: VMAF of the chosen hardware settings at or above the x264 default
  on the reference segment (recorded here; CI runners have no GPU, so CI
  covers the x264 path and the fallback logic).
- Timing: `tests/workflow_timing.py` before and after on the same machine.

## Short-clip benchmark (20 clips of 13 s, direct FFmpeg)

| Encoder | 1 at a time | 2 at a time | 4 at a time |
|---|---|---|---|
| x264 veryfast CRF 20 | 0.9x real time | 0.9x | 0.9x |
| NVENC p5 CQ 27, GPU decode | 4.7x | 5.3x | 5.6x |

x264 does not gain from parallel cuts (and long clips got slower), so it
cuts one at a time; NVENC uses two (consumer cards limit concurrent sessions).
x264 speed on this laptop varies between runs (1.8x on the 60 s segment
earlier), most likely CPU throttling under sustained load; compare runs made
back to back only.

## Results (11 November 2026, same machine and video, back to back)

`tests/workflow_timing.py`, 20 clips of 13 s (260 s of video), source
source backend; `VIZORPLAY_VIDEO_ENCODER=software` forces the old path.

| Step | Software (x264) | Automatic (NVENC here) |
|---|---|---|
| Render one 13 s preview | 14.8 s | 3.2 s |
| Export 20 clips as a reel | 347 s | 52 s |
| Export 20 individual clips | 350 s | 51 s |

What changed:

- `app/video_encoder.py`: detection (once per FFmpeg binary), CRF to CQ
  mapping, worker counts, labels.
- Exports log "Encoding with graphics card (NVIDIA NVENC)" or "software
  (x264)". A hardware failure switches the job to x264 with a log line; a reel
  re-cuts every part so its parts are never mixed. Analysis reels follow the
  same rule; single previews and analysis clips simply retry in software.
- Reels cut their parts in parallel when the encoder benefits (NVENC, 2 at a
  time) and join them in order.
- Export settings: "Encoder: Automatic / Software (x264)", saved with the
  project and kept by filter presets; previews now use the export's encoding
  settings instead of fixed defaults.
- The source smoke test passes both ways, including its pixel checks that
  each clip starts on the right frame.

Not covered: Intel, AMD and Apple hardware encoders (those machines keep using
x264 until measured), and CI, whose runners have no GPU; CI exercises the x264
path and the fallback with a simulated failing encoder.
