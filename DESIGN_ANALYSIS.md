# ClipMaker Design Reference Analysis

## Purpose and boundaries

Butter's public website was studied as a reference for visual rhythm, motion, interaction, and responsive composition. ClipMaker will not reproduce Butter's name, copy, proprietary typefaces, illustrations, 3D objects, imagery, or page structure. The goal is to translate its confident editorial motion into an original, task-focused football video workspace.

Observed on 29 September 2026 at desktop (approximately 1034-1200 px wide) and mobile (390 x 844 px), including the full page, navigation, menu, calls to action, story sections, horizontal gallery, accordions, footer, and responsive states.

## Visual language

- The page is predominantly near-white (`#fafafa`) with black typography and carefully isolated bursts of saturated color. Large quiet fields give animated objects room to move.
- Composition alternates between centered statements, strongly asymmetric editorial layouts, oversized media stages, and full-width section bands. Elements often sit partially outside their nominal grid.
- Display type is very large, tight, and neutral-grotesque. Utility text is small, sparse, and often monospaced. The contrast between these scales carries most of the hierarchy.
- Sections are separated by space, tonal changes, and motion rather than borders. Repeated media containers use soft geometry, but their placement is more important than decoration.
- Images and interactive objects are treated as spatial layers. They crop at viewport edges, pass behind fixed interface elements, and reveal through masks.

## Navigation and layering

- Desktop navigation starts as two floating white groups: the primary navigation at upper left and account/action controls at upper right.
- After scrolling, the primary group compresses to a logo and overflow control. It remains fixed while page content passes beneath it.
- Opening navigation expands a white panel downward from the header. A translucent neutral overlay subdues the page, while the header remains above the panel.
- Mobile uses one compact white header containing the mark and a vertical overflow control. The expanded menu occupies almost the full viewport width, uses divided rows, and can scroll independently.
- Observed layer order: 3D/content at the base; compact mobile controls; mobile menu; cookie layer; navigation overlay; header; page-transition mask; modal; full-screen media; custom cursor; loader.

ClipMaker translation: use a persistent command bar with a compact navigation drawer, but retain application-oriented destinations and visible status. Do not hide critical workflow controls behind spectacle.

## Motion system

Butter uses GSAP, ScrollTrigger, custom smooth scrolling, CSS transitions, and WebGL/Three.js. No Web Animations API animations were detected.

### Core easing and timing

The inspected implementation defines these characteristic curves:

| Role | Curve / timing | Observed use |
| --- | --- | --- |
| Enter | `cubic-bezier(0.815, 0.005, 0.810, 0.195)` | Elements leaving a resting state |
| Exit/reveal | `cubic-bezier(0.200, 0.715, 0.205, 0.990)` | Decisive settling motion |
| State change | `cubic-bezier(0.835, 0.120, 0.225, 0.770)` | Drawers, accordions, media swaps |
| Fast settle | `cubic-bezier(0, 0, 0, 1)` | Masked text and UI reveals |
| Header fade | 400 ms | Scroll and navigation state changes |
| Line reveal | 600 ms plus 100 ms delay | Viewport-entered headings |
| Word reveal | 1000 ms with 50 ms stagger | Large statements |
| Accordion/state swap | 400 ms | Active panel changes |
| Media mask/crossfade | about 600 ms | Layered media changes |
| Page mask in/out | 450-500 ms each | Internal page navigation |

### Triggers and states

- Text reveals trigger when content enters the viewport, with an intersection threshold approximately 10% above the bottom edge.
- Masked lines and characters begin around `translateY(60%)` with zero opacity and finish at their natural position and full opacity. Opacity completes earlier than the movement, producing a crisp rather than floaty entrance.
- UI blocks commonly begin at `translateY(30px)` and zero opacity, then settle with the fast curve.
- Horizontal gallery motion is scroll-linked: the section pins around the viewport center and its track translates by the exact overflow distance with linear easing and `scrub: true`.
- Several media layers scale from `0.8` to `1` as their section travels from viewport bottom to top. This is scroll-linked rather than a one-off timed animation.
- Accordions use time-based 400 ms transitions. The active media sits at a higher z-index; incoming and outgoing masks overlap so no blank frame appears.
- Internal navigation raises a fixed white full-viewport mask from the bottom in about 450 ms. Navigation occurs after roughly 500 ms, then the mask retreats toward the top in 500 ms.
- The header fades rather than jumps when its compact state changes.

### Hover, cursor, and microinteractions

- Hover feedback is restrained: opacity, media reveal, subtle displacement, icon rotation, and masked label changes are preferred over large scale jumps.
- Cursor treatment changes by context. Interactive media can replace the standard pointer with a dedicated circular state. A footer color field continuously cycles hue over five seconds and temporarily accelerates in response to pointer speed.
- Accordion icons rotate or flip as the active state changes.
- Cards that expand into a focused media view interpolate toward viewport-relative dimensions while a backing overlay separates the focused layer.
- Interactive controls preserve their footprint during hover; visual response does not reflow surrounding content.

ClipMaker translation: use a contextual `SCRUB` cursor only over the timeline/preview area, masked labels on primary commands, 400 ms drawers, 600 ms section entrances, and gentle pointer-responsive movement on the video preview. Standard inputs retain familiar cursors.

## Scroll and image treatment

- Smooth scrolling is integrated with the animation ticker. Scroll-linked movement remains direct and uses linear interpolation; staged reveals use bespoke easing.
- Major content changes are keyed to the viewport center, not merely first visibility. This makes long sections feel deliberate.
- Media is often clipped by rounded masks or linear-gradient masks. Incoming media layers have higher stacking priority while previous media remains visible beneath.
- Large image fields are allowed to crop at the viewport edge. Small media objects are embedded directly within display sentences to interrupt the typographic rhythm.
- The full-page capture alone is misleading because many sections initialize pale or empty and activate only after a real scroll with dwell time.

## Responsive behavior

- Desktop uses split navigation groups, expansive whitespace, pinned horizontal sequences, and independent floating media.
- Mobile consolidates navigation, stacks editorial compositions, and replaces some complex horizontal movement with natural vertical flow.
- The hero object remains oversized on mobile and is cropped intentionally. Display text drops to about 57 px with a roughly 62 px line height at 390 px width.
- Mobile menu rows enlarge their tap targets and pair labels with square thumbnails/placeholders. Social links use compact monospace styling.
- Responsive changes are compositional, not just scaled-down desktop rules. Pinning and pointer-only effects should be disabled where touch or limited height makes them awkward.

## Accessibility interpretation

The reference's motion should be adapted, not copied wholesale. ClipMaker will:

- honor `prefers-reduced-motion` by removing scroll transforms, stagger, cursor replacement, and loading choreography;
- preserve native focus visibility and keyboard navigation;
- keep motion decorative and never make it the only indicator of application state;
- avoid replacing the cursor on form controls;
- use high-contrast status text and persistent progress semantics.

## ClipMaker design direction

The representative screen will be the **Match Intake workspace**, the first real task in ClipMaker. It will combine:

- a floating, persistent application header with a compact navigation drawer;
- a large editorial workspace title balanced by dense operational controls;
- a match-source URL intake and local video drop area;
- a video/timeline preview with contextual scrub interaction;
- a recent-match rail and persistent processing status;
- restrained lime as a functional selection/progress accent, supported by white, charcoal, cool gray, pitch green, and event colors;
- line-mask entry motion, a short loading transition, responsive re-composition, and stable control dimensions.

This is deliberately an application screen rather than a marketing hero. Butter's confidence, pacing, masking, and layer choreography are the reference; ClipMaker's football workflow and data remain the content.

## Shared cross-platform architecture

### Recommended target

Use one React + TypeScript web frontend for Windows, Linux, and macOS, backed by one local Python service:

```text
Shared React frontend
        |
local HTTP + SSE/WebSocket API
        |
Shared Python ClipMaker engine
```

- **Windows and Linux:** Tauri owns the native window, lifecycle, local service launch, file-dialog bridge, packaging, and updates. It loads the same compiled frontend assets.
- **macOS without Apple Developer Program:** Homebrew installs the source/runtime package and launches the same local Python service plus frontend in the user's default browser. Because no unsigned `.app` bundle is distributed, this route avoids the downloaded-app Gatekeeper path; Homebrew and its dependencies still follow the user's normal macOS security policy.
- **Frontend:** one codebase and one responsive layout. OS-specific behavior is isolated behind a tiny capability adapter for file selection, reveal-in-folder, and window controls.
- **Backend:** retain the existing Python scraping, analysis, and rendering modules. Put a stable API boundary in front of them rather than duplicating logic in TypeScript.
- **Progress:** use Server-Sent Events for one-way scrape/render progress initially. Add WebSockets only if later features require bidirectional real-time control.
- **Migration:** build and validate one screen at a time alongside Streamlit. Replace the Streamlit presentation layer after equivalent workflows are wired and tested; do not rewrite the football engine.

### Why this direction

It produces a genuinely shared interface while preserving the already-working Python domain code. Tauri remains a thin shell instead of becoming a second application. The browser-based macOS distribution is the practical no-fee compromise: it cannot provide a notarized native `.app`, but it can provide a repeatable Homebrew install and update path without asking users to override Gatekeeper for an unsigned bundle.

## Acceptance criteria for the representative screen

- It is an actual Match Intake workspace at first load, not a landing page.
- Desktop and mobile compositions are intentionally different and remain usable from 390 px upward.
- Header, drawer, loading mask, hover states, timeline scrub, and reduced-motion behavior are implemented.
- Typography, spacing, and motion values follow this analysis without importing Butter assets or proprietary fonts.
- Browser comparison is performed at desktop and mobile sizes, with at least two refinement passes after the initial implementation.
- The existing release launcher can still load the frontend and hand off to the local ClipMaker service.
