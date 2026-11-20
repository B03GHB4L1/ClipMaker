"""Source-level guards for shared UI regressions, alongside browser checks."""
from pathlib import Path
import json
import re
import unittest

UI = Path(__file__).resolve().parents[1] / "ui"


class SharedUiTests(unittest.TestCase):
    def test_ball_respects_reduced_motion_and_limits_rendering_cost(self):
        source = (UI / "app.js").read_text(encoding="utf-8")
        self.assertIn('if (reducedMotion.matches) return;', source)
        self.assertNotIn('preserveDrawingBuffer: true', source)
        self.assertIn('time - lastFrame < 1000 / 30', source)
        self.assertIn('if (reducedMotion.matches && stillRendered) return;', source)

    def test_vizorplay_brand_and_footer_version(self):
        for name in ("index.html", "filters.html", "analysis.html", "annotate.html"):
            source = (UI / name).read_text(encoding="utf-8")
            # The brand panel shows the wordmark; the button's label names it.
            self.assertIn('<span class="cm-logo" aria-hidden="true"><img src="assets/brand/vizorplay-wordmark.svg" alt=""', source)
            self.assertIn('<link rel="icon" href="assets/brand/vizorplay-mark.svg" type="image/svg+xml" />', source)
            self.assertIn('<span>VizorPlay</span><span>Version 1.0</span>', source)
            self.assertNotIn("ClipMaker", source)
            self.assertNotIn("<sup>", source)
            title = re.search(r"<title>(.*?)</title>", source).group(1)
            self.assertIn("VizorPlay", title)
            self.assertNotIn("1.0", title)
        for name in ("mark", "wordmark", "lockup"):
            for suffix in ("", "-on-dark"):
                svg = (UI / f"assets/brand/vizorplay-{name}{suffix}.svg").read_text(encoding="utf-8")
                self.assertTrue(svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '), name)
                self.assertIn("#1C9938", svg)
                self.assertNotIn("<script", svg)
        config = json.loads((UI.parent / "src-tauri/tauri.conf.json").read_text())
        self.assertEqual(config["productName"], "VizorPlay")
        self.assertEqual(config["version"], "1.0.0")
        self.assertEqual(config["identifier"], "com.b4l1.clipmaker")
        for name in ("package.json", "package-lock.json"):
            package = json.loads((UI.parent / name).read_text())
            self.assertEqual(package["name"], "vizorplay-desktop")
            self.assertEqual(package["version"], "1.0.0")
        asset = (UI / "assets/vizorplay-football.glb").read_bytes()
        self.assertEqual(asset[:4], b"glTF")
        scene = json.loads(asset[20:20 + int.from_bytes(asset[12:16], "little")])
        nodes = [node.get("name", "") for node in scene["nodes"]]
        # The ball carries the glasses mark, not the wordmark.
        self.assertIn("Embossed VizorPlay visor", nodes)
        self.assertIn("Embossed VizorPlay play mark", nodes)
        self.assertNotIn("Emerald chrome VizorPlay", nodes)
        self.assertTrue((UI / "assets/vizorplay-football.png").is_file())

    def test_app_icon_is_the_mark_on_a_transparent_background_with_white_lenses(self):
        from PIL import Image
        icon = Image.open(UI.parent / "src-tauri/icons/icon.png").convert("RGBA")
        width, height = icon.size
        self.assertEqual(icon.getpixel((4, 4))[3], 0)
        self.assertEqual(icon.getpixel((width // 2, height - 4))[3], 0)
        # Centre of the left lens is opaque white.
        self.assertEqual(icon.getpixel((width // 4, height // 2)), (255, 255, 255, 255))
        # The Windows installer shows the same icon, not NSIS's default box.
        bundle = json.loads((UI.parent / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))["bundle"]
        self.assertEqual(bundle["windows"]["nsis"]["installerIcon"], "icons/icon.ico")
        self.assertIn("icons/icon.ico", bundle["icon"])
        sizes = Image.open(UI.parent / "src-tauri/icons/icon.ico").info["sizes"]
        self.assertIn((256, 256), sizes)
        self.assertIn((16, 16), sizes)
        # The Mac app needs its own .icns (Tauri cannot make one from a 1024px PNG).
        self.assertIn("icons/icon.icns", bundle["icon"])
        mac = Image.open(UI.parent / "src-tauri/icons/icon.icns")
        self.assertIn((512, 512, 2), mac.info["sizes"])
        self.assertEqual(mac.convert("RGBA").getpixel((4, 4))[3], 0)

    def test_windows_app_opens_maximized(self):
        shell = (UI.parent / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
        self.assertIn(".maximized(cfg!(windows) || config.maximized)", shell)

    def test_open_folder_brings_the_folder_window_to_the_front(self):
        # Explorer opens on the engine's behalf; the app lets it take the foreground first.
        shell = (UI.parent / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
        self.assertIn("AllowSetForegroundWindow(ASFW_ANY)", shell)
        self.assertIn("generate_handler![allow_foreground, raise_folder_window]", shell)
        # Explorer can still open behind; the app (in front) raises the window for that folder.
        self.assertIn('"CabinetWClass"', shell)
        self.assertIn("SetForegroundWindow(search.found)", shell)
        # Without an app manifest and a grant, Tauri refused the pages' calls
        # ("Command allow_foreground not allowed by ACL"), so nothing came to the front.
        build = (UI.parent / "src-tauri/build.rs").read_text(encoding="utf-8")
        self.assertIn('commands(&["allow_foreground", "raise_folder_window"])', build)
        config = json.loads((UI.parent / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
        self.assertTrue(config["app"]["withGlobalTauri"])
        capability = json.loads((UI.parent / "src-tauri/capabilities/engine-pages.json").read_text(encoding="utf-8"))
        self.assertEqual(capability["windows"], ["main"])
        self.assertEqual(capability["remote"]["urls"], ["http://127.0.0.1:*/*"])  # the local engine only
        self.assertNotIn("core:default", capability["permissions"])  # no window or webview APIs
        self.assertEqual(capability["permissions"],
                         ["core:app:allow-version", "allow-allow-foreground", "allow-raise-folder-window"])
        helper = (UI / "save-clip.js").read_text(encoding="utf-8")
        self.assertIn('invoke("allow_foreground")', helper)
        self.assertRegex(helper, r"await allowForeground\(\);\s*const \{ folder \} = await post\(apiPath\);")
        self.assertIn('invoke("raise_folder_window", { folder })', helper)
        self.assertIn("await revealFolder(`/api/saved/", helper)
        self.assertIn("await revealFolder(`/api/jobs/${finishedJobId}/reveal`)", (UI / "filters.js").read_text(encoding="utf-8"))
        # Every Open folder button uses the helper; none calls a reveal endpoint directly.
        for path in [*UI.glob("*.js"), *UI.glob("*.html"), *(UI / "analysis").rglob("*.js")]:
            source = path.read_text(encoding="utf-8")
            if path.name != "save-clip.js":
                self.assertNotRegex(source, r"(post|apiRequest|fetch)\(`/api/(saved|jobs)/[^`]*/reveal", path.name)
            if "Open folder" in source and path.name != "save-clip.js":
                self.assertIn("data-reveal-export", source, path.name)
        self.assertIn('invoke("allow_foreground")', (UI / "update.js").read_text(encoding="utf-8"))

    def test_projects_can_be_deleted_from_intake_and_the_projects_dialog(self):
        projects = (UI / "projects.js").read_text(encoding="utf-8")
        self.assertIn("/delete`", projects)
        self.assertIn("moves to the project-trash folder", projects)  # asks first, says it is recoverable
        self.assertIn("row.append(link, deleteButton(project", projects)
        self.assertIn("unsaved.splice(index, 1)", projects)  # no saves queued for a deleted project
        app = (UI / "app.js").read_text(encoding="utf-8")
        self.assertIn("item.append(button, deleteButton(match))", app)
        self.assertIn("if (detail.wasActive) await openProject(projects[0]);", app)
        self.assertIn("const fresh = await newProject();", app)  # deleting the last one leaves a listed blank project
        self.assertIn(".project-delete", (UI / "compact.css").read_text(encoding="utf-8"))

    def test_shot_marker_size_grows_linearly_with_xg(self):
        component = (UI.parent / "app/smp_component/frontend/index.html").read_text(encoding="utf-8")
        self.assertIn("const size = 6 + 40 * Math.max(0, Math.min(1, shot.xG));", component)
        size = lambda xg: 6 + 40 * xg
        self.assertGreaterEqual(size(0.94) - size(0.76), 7)  # a visible step between big chances

    def test_full_event_table_fills_its_pop_up(self):
        # compact.css caps the Intake preview table at 160px; that cap must not reach the pop-up.
        css = (UI / "compact.css").read_text(encoding="utf-8")
        self.assertIn(".event-dialog .event-dialog-table { max-height: none;", css)
        self.assertLess(css.index(".event-table-wrap { max-height: 160px; }"),
                        css.index(".event-dialog .event-dialog-table { max-height: none;"))

    def test_intake_video_has_no_play_button_over_the_picture(self):
        # It covered the centre spot at kick-off; the ▶ in the control bar plays and pauses.
        for name in ("index.html", "app.js", "styles.css"):
            self.assertNotIn("play-button", (UI / name).read_text(encoding="utf-8"), name)
        self.assertIn("data-player-toggle", (UI / "index.html").read_text(encoding="utf-8"))
        self.assertIn('playerToggle.addEventListener("click", togglePlayback)', (UI / "app.js").read_text(encoding="utf-8"))
        # Play sits in the middle of the stepping buttons: −1f ▶ +1f.
        html = (UI / "index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r">−1f</button></span\s*><button[^>]*data-player-toggle[^>]*>▶</button\s*><span class=\"step-group\" role=\"group\" aria-label=\"Step forward\"")

    def test_switching_period_keeps_the_playhead_unless_the_period_has_a_kickoff(self):
        # 1H -> 2H used to send the playhead back to 0 because an unset period's
        # 00:00:00 is only a placeholder, and it reloaded the same video.
        app = (UI / "app.js").read_text(encoding="utf-8")
        self.assertIn('const markerSet = button.dataset.markerSet === "true";', app)
        self.assertIn("markerSet ? parseClock(button.dataset.marker) : (sameFile ? currentSeconds() : 0)", app)
        self.assertIn("if (!sameFile && activeMatch.id && sourceOf(button.dataset.period))", app)  # reload only for another file

    def test_every_video_page_keeps_the_sound_output_open(self):
        # Pressing play after a long pause froze the picture for ~2.7s while the browser reopened
        # the audio output; a silent running stream keeps it open (measured: 0 of 5 stalls vs 4 of 7).
        module = (UI / "audio-warm.js").read_text(encoding="utf-8")
        self.assertIn("const IDLE_MS = 5 * 60 * 1000;", module)  # released when nobody is watching
        self.assertIn("if (document.hidden) release();", module)
        # Warmed by the first click or key press, ahead of play, so a fresh clip or page starts at once.
        self.assertIn('for (const name of ["pointerdown", "keydown"])', module)
        self.assertIn("opened.state !== \"running\"", module)  # never claims a stream that did not start
        for name in ("index.html", "filters.html", "analysis.html", "annotate.html"):
            self.assertIn('src="audio-warm.js?v=2"', (UI / name).read_text(encoding="utf-8"), name)

    def test_intake_intro_reads_cleanly(self):
        html = (UI / "index.html").read_text(encoding="utf-8")
        self.assertIn("Clip match footage from event data in one seamless experience.", html)
        self.assertNotIn("footage footage", html)

    def test_watched_clips_are_saved_by_the_engine_not_browser_downloads(self):
        # The desktop app windows ignore <a download>, so those buttons did nothing there.
        for name in ("filters.js", "analysis/tabs/event-tab.js", "analysis/tabs/comparison.js", "analysis/tabs/tactical.js"):
            source = (UI / name).read_text(encoding="utf-8")
            self.assertIn("save-clip.js", source, name)
            self.assertNotIn("download: clip.file", source, name)
            self.assertNotIn("download: reel.file", source, name)
            self.assertNotIn("download: slot.file", source, name)
            self.assertNotIn('download.download = `clip-', source, name)
        self.assertIn('<button type="button" data-render-download hidden>Save clip</button>',
                      (UI / "filters.html").read_text(encoding="utf-8"))
        helper = (UI / "save-clip.js").read_text(encoding="utf-8")
        self.assertIn("/api/media/${encodeURIComponent(id)}/save", helper)
        self.assertIn("/api/saved/${encodeURIComponent(saved.id)}/reveal", helper)
        self.assertIn("Open folder", helper)
        self.assertIn(".saved-popup", (UI / "design.css").read_text(encoding="utf-8"))

    def test_intake_brand_screen_lingers_then_peels_away(self):
        app = (UI / "app.js").read_text(encoding="utf-8")
        styles = (UI / "styles.css").read_text(encoding="utf-8")
        hold = int(re.search(r"const WIPE_HOLD_MS = (\d+);", app).group(1))
        self.assertGreaterEqual(hold, 1000)  # stays up a moment longer than the page load
        self.assertLessEqual(hold, 2000)
        # The engine connects straight away; only the reveal waits.
        self.assertRegex(app, r'addEventListener\("load", \(\) => \{\s*connectApi\(\);\s*setTimeout')
        self.assertIn("transform: translateY(-100%);", styles)  # peels up rather than snapping shut
        self.assertIn("page-wipe-name 0.6s ease-out backwards", styles)  # the name can fade out again
        reduced = styles[styles.index("@media (prefers-reduced-motion"):]
        self.assertRegex(reduced, r"\.page-wipe \{\s*display: none;")

    def test_attack_label_adds_room_rather_than_shrinking_tactical_pitches(self):
        source = (UI / "analysis" / "tabs" / "tactical.js").read_text(encoding="utf-8")
        self.assertIn('note.text === "ATTACK ->") ? 26 : 0', source)
        self.assertIn("t: 64 + labelRoom", source)  # phone layout
        self.assertIn("Math.max(420, window.innerHeight - 120) + labelRoom", source)  # window-height cap

    def test_chart_pictures_are_saved_by_the_engine_not_browser_downloads(self):
        component = (UI.parent / "app" / "smp_component" / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/images/save"', component)
        self.assertIn('type: "vizorplay:saved"', component)
        host = (UI / "analysis" / "component-host.js").read_text(encoding="utf-8")
        self.assertIn('message.type === "vizorplay:saved"', host)
        self.assertIn("showSaved(message.saved", host)
        # Plotly's own camera button also downloads; it is swapped for one that saves.
        helper = (UI / "save-clip.js").read_text(encoding="utf-8")
        self.assertIn('"toImage"', helper)
        for name in ("analysis/tabs/comparison.js", "analysis/tabs/tactical.js"):
            source = (UI / name).read_text(encoding="utf-8")
            self.assertNotIn("{ ...item.config, responsive: true })", source.replace("plotlyConfig({ ...item.config, responsive: true }", ""), name)
            self.assertNotIn("{ ...element.config, responsive: true })", source.replace("plotlyConfig({ ...element.config, responsive: true }", ""), name)

    def test_video_lab_reel_is_picked_moment_by_moment(self):
        source = (UI / "analysis" / "tabs" / "tactical.js").read_text(encoding="utf-8")
        self.assertIn('"vl_selected_moment_", "vl_reel_moments_"', source)  # picks saved per playlist
        self.assertIn("Add moment ${index + 1} to the reel", source)
        self.assertIn("Build reel · ${count}", source)
        self.assertIn("plays in match order", source)
        self.assertIn("Your reel picks have changed since this reel was built", source)
        css = (UI / "analysis" / "native.css").read_text(encoding="utf-8")
        self.assertIn(".native-reel-check", css)
        self.assertIn("margin: 0", css[css.index(".native-reel-check {"):][:200])  # not the global label margin

    def test_removed_progress_has_no_markup_or_handlers(self):
        for name in ("index.html", "app.js", "styles.css", "compact.css"):
            source = (UI / name).read_text(encoding="utf-8")
            for obsolete in ("step-track", "setWorkflowStep", "data-step-label", "data-workflow-progress"):
                self.assertNotIn(obsolete, source, name)

    def test_all_screens_use_same_shared_style_versions(self):
        versions = []
        for name in ("index.html", "filters.html", "analysis.html", "annotate.html"):
            source = (UI / name).read_text(encoding="utf-8")
            self.assertIn('class="app-footer"', source)
            self.assertIn("Version 1.0", source)
            versions.append(re.findall(r'href="((?:styles|compact|design)\.css\?v=\d+)"', source))
        for other in versions[1:]:
            self.assertEqual(versions[0], other)

    def test_annotate_offered_beside_every_clip_preview_but_not_home(self):
        # docs/TELESTRATION_PLAN.md: Annotate wherever a clip can be watched, except the Intake (home) page.
        self.assertIn("Annotate", (UI / "save-clip.js").read_text(encoding="utf-8"))
        self.assertIn("data-render-annotate", (UI / "filters.html").read_text(encoding="utf-8"))
        self.assertIn("annotateClip(result.file.url", (UI / "filters.js").read_text(encoding="utf-8"))
        for name in ("index.html", "app.js"):
            self.assertNotIn("annotate", (UI / name).read_text(encoding="utf-8").lower(), name)

    def test_export_line_offers_annotate_for_the_clip_in_the_player(self):
        # User request: Annotate sits on the Clips screen's export line, not only behind "Render this clip".
        html = (UI / "filters.html").read_text(encoding="utf-8")
        bar = html[html.index('<div class="export-bar">'):html.index("data-export-button")]
        self.assertIn("data-annotate-focused", bar)
        script = (UI / "filters.js").read_text(encoding="utf-8")
        self.assertIn("annotateButton.disabled = !clips.length || !hasFootage();", script)
        handler = script[script.index('annotateButton.addEventListener("click"'):]
        self.assertIn("const clip = focused();", handler)
        self.assertIn('apiRequest("/api/previews/render"', handler)
        self.assertIn("annotateClip(result.file.url", handler)

    def test_board_from_frame_is_wired_and_hides_the_transport_while_marking(self):
        # M7: the board button opens the pitch marks; transport and timeline step aside so the frame stays put.
        html = (UI / "annotate.html").read_text(encoding="utf-8")
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        css = (UI / "annotate.css").read_text(encoding="utf-8")
        self.assertIn('data-board aria-expanded="false" aria-controls="calibrate-panel"', html)
        self.assertEqual(html.count("data-calib-hide"), 2)
        self.assertIn(".annotate-transport[hidden], .annotate-timeline[hidden], .annotate-calibrate[hidden] { display: none; }", css)
        for hook in ("openCalibration", "findPlayers", "downloadModel", "stopCalibrationJob", "removeCalibrationPoint", "closeCalibration"):
            self.assertIn(hook, script)
        # Boards are drawn in the preview, the screenshot and the exported overlay.
        self.assertEqual(script.count("drawBoard("), 3)
        # The download is offered, never started on its own.
        self.assertIn('$("[data-calib-download]").onclick = downloadModel;', script)

    def test_annotate_markup_keeps_every_hook_the_editor_script_uses(self):
        # The editor's markup was redesigned; annotate.js finds its controls by data attribute.
        html = (UI / "annotate.html").read_text(encoding="utf-8")
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        built = {"data-head", "data-lane-freeze", "data-freeze-seconds", "data-bar", "data-mark"}  # made by the script itself
        hooks = set(re.findall(r'\$\("\[(data-[a-z-]+)', script)) | set(re.findall(r'querySelector(?:All)?\("\[(data-[a-z-]+)', script))
        self.assertGreater(len(hooks), 20)
        for hook in sorted(hooks - built):
            self.assertIn(hook, html, hook)
        # Drawn icons, not Unicode glyphs, on the transport and freeze list.
        self.assertNotIn("&#9664;", html)
        self.assertNotIn('textContent: "×"', script)
        self.assertIn('classList.toggle("is-playing", playing)', script)

    def test_annotate_drawing_tools_stand_apart_from_select_and_player_tools(self):
        # User request: the rail holds drawing tools only; Select sits in the command bar; Ring, Follow and Token with Players.
        html = (UI / "annotate.html").read_text(encoding="utf-8")
        section = lambda start, end: html[html.index(start):html.index(end, html.index(start))]
        rail = section('<div class="annotate-tools"', '<div class="annotate-centre">')
        self.assertEqual(re.findall(r'data-tool="([a-z]+)"', rail), ["arrow", "line", "freehand", "zone", "spotlight", "text"])
        self.assertEqual(re.findall(r'data-tool="([a-z]+)"', section('<div class="annotate-bar">', "</div>\n    <p")), ["select"])
        self.assertEqual(re.findall(r'data-tool="([a-z]+)"', section('<section class="annotate-player-tools"', "</section>")), ["ring", "follow", "token"])

    def test_annotate_says_where_to_start_and_what_each_control_does(self):
        # User request 2026-11-17: headed tool groups, plain labels, a start guide and a bigger video.
        html = (UI / "annotate.html").read_text(encoding="utf-8")
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        css = (UI / "annotate.css").read_text(encoding="utf-8")
        rail = html[html.index('<div class="annotate-tools"'):html.index('<div class="annotate-centre">')]
        self.assertEqual(re.findall(r'class="annotate-group-title" id="[a-z-]+">([A-Za-z ]+)<', rail), ["Draw", "Highlight", "Write"])
        side = html[html.index('<section class="annotate-player-tools"'):html.index("</section>", html.index('<section class="annotate-player-tools"'))]
        self.assertIn(">Mark a player</h2>", side)
        self.assertIn(">Add at this frame</h2>", side)
        self.assertIn("data-freeze ", side)
        self.assertIn("data-board ", side)
        self.assertEqual(side.count("<small>"), 5)  # every player and insert button says what it does
        transport = html[html.index('<div class="annotate-transport"'):html.index("</div>", html.index('<div class="annotate-transport"'))]
        self.assertNotIn("data-freeze", transport)  # it overflowed the transport row
        # Vague tracking labels are gone; the buttons name their action.
        for vague in ("Still right", "Next check"):
            self.assertNotIn(vague, html + script)
        for label in ("Confirm this frame", "Next frame to check", "Track again from here", "Check the tracking", "Fix the tracking"):
            self.assertIn(label, html)
        # A blank clip shows the steps to a first export; empty lanes say what will appear.
        self.assertIn('"How to start"', script)
        self.assertEqual(html.count("data-empty="), 2)
        self.assertIn("content: attr(data-empty)", css)
        # The video takes the height the bars, transport and footer leave.
        self.assertIn("calc((100svh - 200px) * var(--clip-ratio, 1.7778))", css)
        self.assertNotIn("100svh - 300px", css)

    def test_annotate_select_tool_box_selects_and_deletes_several(self):
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        # A drag on empty picture draws a selection box; every drawing it touches is selected.
        self.assertIn('gesture = { type: "marquee"', script)
        self.assertIn("return r >= x0 && l <= x1 && b >= y0 && t <= y1;", script)
        # Shift+click adds or removes one; a drag on one of them moves them all, as one undo step.
        self.assertIn("if (event.shiftKey && hit) {", script)
        self.assertIn('gesture = { type: "group"', script)
        self.assertIn("function moveGroup(", script)
        # Delete removes every selected drawing at once.
        self.assertIn("const ids = new Set(selectedIds.length ? selectedIds : selectedId ? [selectedId] : []);", script)

    def test_annotate_freezes_and_boards_delete_from_the_timeline(self):
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        css = (UI / "annotate.css").read_text(encoding="utf-8")
        # Each block on the Freezes lane has a delete cross; a click selects the block and Delete removes it.
        self.assertIn('remove.dataset.freezeRemove = String(freeze.atFrame);', script)
        self.assertIn("removeFreeze(Number(removeButton.dataset.freezeRemove))", script)
        self.assertIn("if (selectedFreeze !== null && !selectedIds.length) return removeFreeze(selectedFreeze);", script)
        self.assertIn(".annotate-lane-freeze:hover .annotate-lane-remove", css)

    def test_annotate_handles_are_thin_and_cursors_say_what_a_drag_does(self):
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        # Small, thin handles: what catches the pointer stays bigger than what is drawn.
        draw = script[script.index("function drawHandle("):script.index("function drawSquareHandle(")]
        self.assertIn("ctx.lineWidth = ratio;", draw)
        self.assertNotIn("ctx.arc(x, y, handleRadius()", draw)
        # Two-headed arrows on size handles and box corners, the four-headed move arrow on a drawing.
        self.assertIn('const CORNER_CURSORS = { nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize" };', script)
        self.assertIn('if (handle.index === "r") return "ew-resize";', script)
        self.assertIn('if (handle.index === "h") return "ns-resize";', script)
        self.assertIn("canvas.style.cursor = cursorAt(at);", script)

    def test_annotate_text_follows_players(self):
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        # Text placed or dropped on a followed player links to them; dragging linked text changes only
        # where it sits beside them, never the player's tracked box.
        self.assertIn("const link = linkToPlayerAt(point);", script)
        apply = script[script.index("function applyEdit("):]
        text = apply[apply.index('if (original.kind === "text")'):apply.index('if (type === "handle" && (index === "r"')]
        self.assertIn("dx: Math.round((point.dx + dx) * 1e5) / 1e5", text)
        self.assertNotIn("correctTrack", text)

    def test_annotate_zone_corners_on_followed_players(self):
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        # A first corner on a player is placed for this frame before the close check (it is not an [x, y]),
        # a click on that player again closes the zone, and repeated corners are dropped.
        self.assertIn("toPixels(resolvePoint(zoneDraft[0], tracks(), frameNow()))", script)
        self.assertIn("(isLinked(corner) && sameCorner(zoneDraft[0], corner))", script)
        self.assertIn("const corners = zoneDraft ? zoneCorners(zoneDraft) : [];", script)
        self.assertNotIn("zoneDraft.pop()", script)

    def test_annotate_critique_fixes_hold(self):
        html = (UI / "annotate.html").read_text(encoding="utf-8")
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        css = (UI / "annotate.css").read_text(encoding="utf-8")
        # The shared control and hover rules must not outrank Play, Save screenshot or pressed tools.
        self.assertIn(".annotate-main :where(.annotate-command, .annotate-shot,", css)
        self.assertIn(".annotate-main :where(button, select):where(:hover:not(:disabled))", css)
        self.assertNotIn(".annotate-main :is(.annotate-command", css)
        self.assertNotIn(".annotate-main :is(button, select):hover", css)
        # One meaning per colour: lime is the primary action, ink the active tool.
        self.assertIn(".annotate-main .annotate-export-button { border-color: var(--cm-accent); background: var(--cm-accent);", css)
        self.assertNotIn(".annotate-main .annotate-shot { border-color: var(--cm-accent)", css)  # one primary action
        self.assertNotIn('[data-tool="follow"][aria-pressed="true"]', css)
        # Shortcut hints are readable (muted ink, not pale grey at 9px).
        self.assertNotIn("#9a9d96", css)
        self.assertNotIn("font-size: 9px", css)
        # Narrow windows keep settings beside the video.
        narrow = css[css.index("@media (max-width: 1100px)"):css.index("@media (max-width: 720px)")]
        self.assertIn("grid-template-columns: 76px minmax(0, 1fr) 216px", narrow)
        # Delete sits in the command bar and needs a selection; the page has one h1.
        bar = html[html.index('<div class="annotate-commands">'):html.index("</div>", html.index('<div class="annotate-commands">'))]
        self.assertIn('data-delete disabled', bar)
        self.assertEqual(html.count("data-delete"), 1)
        self.assertIn('$("[data-delete]").disabled = !item && !many && !freeze;', script)
        self.assertIn("<h1 data-annotate-title>", html)
        # aria-pressed goes on tool buttons, never on the canvas.
        self.assertIn('querySelectorAll("button[data-tool]")', script)
        # Freezes start closed and open when the first one is added.
        self.assertIn("<details data-freeze-panel>", html)
        self.assertIn('$("[data-freeze-panel]").open = true', script)

    def test_annotate_drawings_lane_sets_timing_by_dragging(self):
        html = (UI / "annotate.html").read_text(encoding="utf-8")
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        self.assertIn("data-drawing-lane", html)
        self.assertIn("data-drawing-head", html)
        lane = script[script.index('const lane = $("[data-drawing-lane]");\n  let drag'):]
        self.assertIn("selectDrawing(item)", lane)
        self.assertIn("setTiming(key,", lane)
        self.assertIn("renderDrawingLane();", script[script.index("const renderList"):])

    def test_annotate_exports_video_with_progress_and_cancel(self):
        # M4: the page draws overlays with the preview's own code and sends them to the engine.
        html = (UI / "annotate.html").read_text(encoding="utf-8")
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        bar = html[html.index('<div class="annotate-commands">'):html.index("</div>", html.index('<div class="annotate-commands">'))]
        self.assertIn("data-export ", bar)
        for hook in ("data-export-panel", "data-export-text", "data-export-progress", "data-export-cancel"):
            self.assertIn(hook, html)
        flow = script[script.index("const exportVideo"):script.index("const cancelExport")]
        self.assertIn("await save();", flow)  # the engine renders the saved document
        self.assertIn("drawItem(context,", flow)  # same drawing code as the preview
        self.assertIn("/overlays`", script)  # batched: thousands of single requests exhaust local ports
        self.assertIn("key !== previous", flow)  # only frames where the drawings change are sent
        self.assertIn("showSaved(job.result.saved, \"Video\")", flow)
        self.assertIn("/api/editor-jobs/${run.job.id}/cancel", script)

    def test_annotate_tracks_towards_the_next_keyframe_and_retracks_before_a_correction(self):
        # M5: a span with a keyframe after it tracks back from there too, so it arrives without a jump;
        # correcting a frame re-tracks the span before it once the span after it is done.
        script = (UI / "annotate.js").read_text(encoding="utf-8")
        start = script[script.index("async function startTracking"):script.index("function runQueued")]
        self.assertIn("to_box: next", start)
        self.assertIn("runQueued(trackId)", script[script.index("async function pollTracking"):])
        correct = script[script.index("const correctTrack"):]
        self.assertIn("queued.set(trackId, [{ start: Math.max(...earlier), limit: frame - 1 }])", correct)

    def test_export_line_looks_the_same_with_settings_open_or_closed(self):
        # The buttons stay on the first row and the settings toggle sits under them either way.
        css = (UI / "editor.css").read_text(encoding="utf-8")
        self.assertIn(".export-bar .export-settings { order: 5; flex-basis: 100%; }", css)
        self.assertNotIn(".export-settings[open] { order", css)
        self.assertNotIn(":has(.export-settings[open])", css)
        # The toggle's own row stays short so the export line fits above the footer at 1440x900.
        self.assertIn(".export-bar .export-settings > summary { min-height: 28px; }", css)

    def test_annotate_page_scrolls_past_the_window(self):
        # The editor shares the analysis shell, which locks the page to the window
        # (overflow hidden, height 100dvh); the editor's lanes and panels sit below it.
        self.assertIn('class="analysis-page annotate-page"', (UI / "annotate.html").read_text(encoding="utf-8"))
        css = (UI / "annotate.css").read_text(encoding="utf-8")
        self.assertIn("body.annotate-page { overflow-y: auto; height: auto; min-height: 100vh; }", css)
        self.assertIn(".annotate-page .annotate-main { flex: 1 0 auto; }", css)

    def test_intake_has_no_sample_kickoff_markers(self):
        source = (UI / "index.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'data-marker="([^"]+)"', source), ["00:00:00"] * 5)
        self.assertRegex(source, r'aria-hidden="true"\s+inert')

    def test_geist_is_bundled_and_identical_in_chart_component(self):
        font = (UI / "assets/fonts/GeistMono-Variable.ttf").read_bytes()
        self.assertEqual(font[:4], b"\x00\x01\x00\x00")
        chart = UI.parent / "app/smp_component/frontend"
        self.assertEqual(font, (chart / "fonts/GeistMono-Variable.ttf").read_bytes())
        self.assertIn("SIL OPEN FONT LICENSE", (UI / "assets/fonts/OFL-GeistMono.txt").read_text(encoding="utf-8"))
        for name in ("index.html", "filters.html", "analysis.html"):
            self.assertIn('href="design.css?', (UI / name).read_text(encoding="utf-8"))
        self.assertNotIn("fonts.googleapis.com", (chart / "index.html").read_text(encoding="utf-8"))

    def test_analytical_chart_fonts_and_selected_tab_contrast(self):
        for name in ("comparison_helpers.py", "tactical_page.py"):
            source = (UI.parent / "app/analysis_core" / name).read_text(encoding="utf-8")
            self.assertNotIn('family="Inter, sans-serif"', source)
            self.assertNotIn('family="Space Grotesk, Inter, sans-serif"', source)
            self.assertIn('family="Geist Mono, monospace"', source)
        css = (UI / "analysis/native.css").read_text(encoding="utf-8")
        self.assertIn(".native-tabs [role=tab][aria-selected=true] { color: var(--cm-ink);", css)

    def test_analysis_page_has_no_classic_workspace(self):
        # Phase 5 retired the Streamlit workspace: no iframe, no classic switch.
        page = (UI / "analysis.html").read_text(encoding="utf-8")
        scripts = "".join((UI / name).read_text(encoding="utf-8") for name in ("analysis.js", "analysis/native.js"))
        self.assertNotIn("<iframe", page)
        for token in ("ui=classic", "/api/analysis\"", "classicUrl", "data-analysis-frame"):
            self.assertNotIn(token, scripts)

if __name__ == "__main__":
    unittest.main()
