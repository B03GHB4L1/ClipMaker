# Ship checklist: VizorPlay 1.0

Nothing below happens on its own. Each step that changes what the public sees
(visibility, tag, Pages, tap) is the owner's call, in this order.

## 1. Before anything goes public

- [ ] CI is green on the latest commit of `B4L1/release-packaging` (Checks, Full
      Desktop E2E, both Mac disk image runs). The Linux build is the first
      compile of the Linux in-app update code, so watch it closely.
- [ ] Release dry-run is green on the latest commit, including the `candidate`
      job (DMGs in `SHA256SUMS` and in `latest.json`).
- [ ] The signing secret `TAURI_SIGNING_PRIVATE_KEY` exists in the repository.
- [ ] The Mac in-app update is built but unproven: after the first release, try
      one update from 1.0 to a test 1.0.1 on a real Mac (Apple Silicon) and note
      whether Gatekeeper asks again. If it fails, say so in the README and page.
- [ ] Open items from the earlier review are settled: `design/chrome_ball`,
      `docs/MAC_INSTALLERS_PLAN.md`, the `Windows/` deletions.
- [ ] Merge PR #8 into `main` only when you say the work is done.

## 2. Release

- [ ] Tag `v1.0.0` on `main`. The publish job in `release.yml` runs only on this
      tag.
- [ ] Check the release page: Windows setup, both Mac disk images, the `.deb`,
      `SHA256SUMS`, `latest.json`.
- [ ] Install each file on a real machine once and open it. Mac: confirm the
      first-launch steps in the README match what macOS shows.
- [ ] Confirm the Windows app finds `latest.json` (Update message appears when
      a newer version is published later).

## 3. Homebrew tap (`B03GHB4L1/vizorplay`, private and empty today)

- [ ] Put the formula made by the release candidate into the tap repository.
- [ ] Check it installs on a clean Mac: `brew tap B03GHB4L1/vizorplay`, then
      `brew install vizorplay`.
- [ ] Make the tap public. Until then the `brew tap` lines in the README and on
      the page do not work for anyone.

## 4. Winget (if used)

- [ ] Submit the manifests the release candidate prepared. Skip if not shipping
      through winget at 1.0.

## 5. The page (`site/`)

Edit when the release exists, before turning Pages on:

- [ ] Hero: replace the "Version 1.0: coming soon" button with a real download
      button; remove the "not released yet" status line.
- [ ] Install tabs: every "Coming soon" button becomes a real link to its file
      on the release page.
- [ ] Footer: change "Version 1.0 (not yet released)" to "Version 1.0".
- [ ] PRODUCT.md and the README: remove "not out yet" and "(coming soon)".
- [ ] Preview at desktop and phone width.
- [ ] Repository Settings, Pages: serve `main`, folder `/site` (or add a deploy
      workflow). Check the live address, then add it to the repository's
      About box.

## 6. Repository visibility

- [ ] Only if the repository is still private: change it to public. Nothing in
      this list does that for you.

## 7. After launch

- [ ] Watch the first Issues. Test one real update from 1.0 to a test 1.0.1.
- [ ] Update docs/RELEASES.md for anything learned.
