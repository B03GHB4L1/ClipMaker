# VizorPlay Working Agreement

## Product Scope
- Maintain one shared frontend for Windows, Linux, and macOS.
- Treat the original applications in `older versions/` as the feature baseline. Record parity in a checklist before claiming completion.
- Preserve the existing exclusion of AI filtering unless the user explicitly changes it.
- Keep the source repository private. Never publish code or change repository visibility.

## User Experience
- Keep screens compact, navigable, responsive, and accessible. Use collapsible sections for detailed controls.
- The compact brand panel contains only VizorPlay and the menu icon, without a version number.
- The displayed application version is 1.0, shown in the footer rather than the app name.
- Display the application version at the bottom of every screen.
- Each project is independent and saved locally, including source metadata, events, video references, period kickoff timing, filters, and export settings.
- Do not erase or overwrite projects when starting a new project. Save before switching; expose loading and error states.

## Engineering
- Read existing implementation and historical OS-specific behavior before editing.
- Preserve unrelated user changes, including moved historical directories. Stage only deliberate changes.
- Use atomic writes and validate API inputs. Do not expose arbitrary filesystem access through the browser API.
- Keep operating-system integrations behind platform adapters. Do not silently disable missing dependencies.
- No Apple Developer membership is available. Do not promise unsigned macOS apps bypass Gatekeeper; document supported installation and launch behavior honestly.

## Verification And Delivery
- Add focused regression tests for each changed behavior and broader tests for shared contracts.
- Exercise scrape, project save/reopen, period alignment, filters, preview edits, exports, and cancellation.
- Check desktop and narrow layouts for overflow, hidden controls, dead actions, and console errors.
- Use GitHub Actions to test Windows, Linux, and macOS; distinguish unit tests, build checks, and actual packaged-app launch tests.
- Commit verified changes with clear messages. Never call the app complete while required checklist items remain unverified or failing.
- Report test failures and external blockers honestly; do not guarantee absence of bugs.
