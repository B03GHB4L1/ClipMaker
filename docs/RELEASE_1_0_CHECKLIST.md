# VizorPlay 1.0 release gate

Updated 25 October 2026. Publication requires the owner's separate instruction.
This checklist records evidence, not a guarantee that software has no bugs.

| Gate | Evidence / next action |
| --- | --- |
| Shared frontend, local isolated projects, no AI filtering | Implemented; existing unit/browser/native acceptance |
| Baseline all-platform checks | E2E 40201098220 and Checks 40201103145 passed at 3be71cc |
| 64 non-AI qualifiers; ANY/ALL and mixed filters | New explicit parity cases in test_release_features.py; hosted run pending |
| Stable shootout anchor after team/player filtering | Regression exposed and fixed; preview and export use original timing data |
| ET1/ET2/PEN timing, corrections, source selection | Synthetic source/time/pixel checks; real-match acceptance remains open |
| Event table, snapshots, chart selection and PNG/GIF | Added real browser journeys; hosted run pending |
| Different-version Windows/DEB upgrades | Controlled same-source 0.9.0 → 1.0.0, then same-version reinstall/uninstall; hosted run pending |
| Previous 1.3 metadata → new 1.0 version reset | Distinct from a normal upgrade; historical installed-package migration remains open (see BRANDING.md). Do not promise a package manager will treat a lower version as an upgrade |
| Homebrew upgrade and project reopen | Controlled local formula 0.9.0 → 1.0.0; hosted run pending |
| Exact tested release artifacts | Receipt/checksum assembly implemented; first candidate run pending |
| Live Scoresway/WhoScored | Earlier local checks passed; Scoresway passed hosted, WhoScored hosted HTTP 403. Retest at release; distinguish external denial |
| Batch scrape / partial failures | Real Scoresway browser batch passed in run 40212549960, with invalid URL report and prior-project preservation |
| Advanced Tactical Video Lab and multi-match moments/reels | Focused numerical/media acceptance passes locally, including multi-project video mapping, saved corrections, shootout anchors and cache invalidation; hosted/browser-native acceptance pending |
| Native chart controls and OS file dialogs | Browser/chart checks do not certify every native-webview interaction; focused physical-device acceptance remains open |
| Public Mac install/update | Prepared formula still needs release asset plus authorized tap publication; tap currently private/empty |
| Public Windows package updates | WinGet manifests prepared; community submission/acceptance still needed |
| Linux updates | Download and install newer DEB; no automatic update repository configured |
| Unsigned installation expectations | Windows security warnings possible; Homebrew source launcher is not a Gatekeeper bypass guarantee |
| Release notes / support / licenses | Existing license and bundled font licenses; final candidate limitations must accompany publication |

Candidate scope: Windows x64 NSIS, Ubuntu 22.04 x64 DEB, and macOS Homebrew
source launcher with the shared frontend in the default browser. Native macOS
app bundles, RPM packages, in-app automatic updates, and certification across
all Linux distributions are not implied by these tests.

Do not mark remaining gates passed based only on unit tests or a successful
build. Link the final candidate run/commit and record any owner-accepted scope
decisions here before claiming full 1.0 readiness.

Local verification for this preparation: 187 Python tests ran, 185 passed and
two OS-specific tests were skipped on Windows. The Node autosave test, workflow
lint and source real-media/cancellation/owner-exit smoke passed. The new hosted
candidate, installer upgrades, live batch and chart download journeys remain
pending until their Actions results exist.

First expanded hosted run 40212549960 exposed fixture assertions comparing
equivalent Windows short/long and macOS symlink paths, a snapshot selection/name
reset, and a Homebrew assertion that rejected retained older kegs. The fixture
paths are now canonicalized, snapshot loading preserves its selection, and the
Homebrew check verifies the actual linked launcher version. Follow-up CI is
required; the earlier run is not a passed candidate.

Checks 40214541214 passed all three platforms at 690f6fc. The corresponding
candidate run passed all source/frozen browser/media layers, installed Homebrew
upgrade/reopen, and the real Scoresway/batch checks. Native Windows/Linux package
lifecycle and candidate assembly were still running. A subsequent visual review
also replaces generated CSV identifiers with saved match/project names. The
Linux runner's stalled Azure WebKit download is addressed by using Ubuntu's
official archive with bounded network retries; required dependencies remain
mandatory.

The published v1.2 Windows ZIP was inspected: it contains source/launcher files,
not an EXE/MSI installer. GitHub lists v1.0, v1.1 and v1.2, with no published
1.3 release. A 1.3 → 1.0 installed-package reset is therefore a precaution for
unreleased test installs, rather than a demonstrated public update channel.
