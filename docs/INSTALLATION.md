# Install and update VizorPlay 1.0

These instructions describe the prepared 1.0 distribution. A candidate artifact
is available only after its Actions run passes; a public release and package
channels must be published separately before their public commands work.

## Windows x64

1. Download the VizorPlay setup `.exe` from the official GitHub release.
2. Close an older VizorPlay window, if open.
3. Run the installer and follow its prompts. It installs for your user account.
4. Open VizorPlay from the Start menu.

Updates install from inside the app. When a newer version is released, the
bottom bar of every screen says "VizorPlay 1.x is available" with an **Update
and restart** button. VizorPlay downloads the new installer, checks it is signed
with VizorPlay's update key (anything else is refused), closes, updates and opens
again by itself. Saved projects are stored separately from the installed program
and are kept. Running a newer setup file by hand also still works.
The prepared installer is unsigned, so Windows may display a security warning.
The release must state its signing status clearly.

WinGet manifests are prepared, but the community package has not been accepted.
Do not advertise `winget install` or `winget upgrade` as available yet.

## Ubuntu 22.04 x64

1. Download the VizorPlay `.deb` file from the official GitHub release.
2. Open a terminal in the folder containing that file.
3. Run `sudo apt install ./` followed by the downloaded filename. For example:

```sh
sudo apt install ./VizorPlay_1.0.0_amd64.deb
```

4. Open VizorPlay from your applications menu.

When a newer version is released, the bottom bar says so and its **Download**
button opens the release page. Close VizorPlay and install the newer DEB with
the same command. APT installs required system dependencies. Linux packages do
not update from inside the app, and no APT repository is configured. Other distributions
and RPM packages are outside the verified candidate scope.

## macOS disk image (Apple Silicon and Intel)

The Mac download is a disk image (`.dmg`) with VizorPlay's engine inside, so
there is nothing else to install and no Terminal. It needs **macOS 14 (Sonoma) or
later on an Apple Silicon Mac** and **macOS 12 (Monterey) or later on an Intel Mac**;
the engine's libraries (numpy, curl_cffi, OpenCV) are built for those versions, and an
older Mac is told so instead of opening the app. Every Apple Silicon Mac can update to
macOS 14 or later; an Intel Mac that stops at macOS 11 or earlier cannot run this image.
Status: CI builds and tests the Apple Silicon image
(`.github/workflows/mac-dmg.yml`) and the Intel image
(`.github/workflows/mac-dmg-intel.yml`), each on a GitHub Mac of its own chip
(macOS 15 or 26 only), and checks the minimum macOS of every file inside each app.
Real Macs and other macOS versions are not tested yet. No VizorPlay release is
published yet, so these steps describe the supported install once it is.

1. **Find your Mac's chip.** Apple menu, **About This Mac**. If it says *Chip:
   Apple M1* (or M2, M3, M4), download `VizorPlay_<version>_aarch64.dmg`. If it
   says *Processor: Intel*, download `VizorPlay_<version>_x64.dmg`. An Apple
   Silicon Mac can also run the Intel file (through Rosetta), but an Intel Mac
   cannot run the Apple Silicon file.
2. **Install.** Open the downloaded file. A window shows VizorPlay and your
   Applications folder with an arrow between them: drag VizorPlay onto
   Applications. Then eject the disk (click the eject button beside it in
   Finder's sidebar).
3. **Open it once, past macOS's check.** VizorPlay is not notarized by Apple,
   because there is no Apple Developer membership. macOS therefore blocks the
   first launch with a message that it cannot verify the app. This is the only
   extra step, and it happens once:
   - **macOS 15 (Sequoia) or later:** open VizorPlay from Applications and close
     the message. Open **System Settings**, **Privacy & Security**, scroll to
     **Security**, find "VizorPlay was blocked", click **Open Anyway**, confirm
     with your password or Touch ID, then click **Open**.
   - **macOS 14 (Sonoma) or earlier:** in Applications, Control-click (or
     right-click) VizorPlay, choose **Open**, then click **Open** again.
   - **From Terminal instead:** `xattr -dr com.apple.quarantine /Applications/VizorPlay.app`
     removes the download flag; then open VizorPlay normally.

   VizorPlay is ad hoc signed so Apple Silicon will run it, but ad hoc signing
   does not satisfy Gatekeeper and nothing here bypasses it: you are telling
   macOS to trust this one app. Later launches open normally.
4. **Updating and removing.** Download the newer disk image and drag VizorPlay
   onto Applications again, choosing **Replace**; your projects stay (they live
   in your user Library, outside the app). Updates do not install themselves on
   macOS yet. To remove VizorPlay, drag it from Applications to the Bin; projects
   stay until you delete them (the local-project picker shows where).

The image's own window repeats the Open Anyway step, so it is seen before the
first launch. A Mac that blocks the app even after Open Anyway, or says it is
damaged, usually has the download flag set by a browser or archive tool; the
Terminal command above clears it.

## macOS Homebrew

Homebrew is an alternative to the disk image and is slower. On macOS, Homebrew builds the VizorPlay app on your Mac during `brew install`,
so VizorPlay opens in its own window like the Windows and Linux apps. No Apple
Developer membership is involved: the app is not notarized by Apple. It opens
because it was built on your Mac rather than downloaded, so macOS does not
quarantine it. This is not a way around Gatekeeper, and it does not promise that
no macOS security prompt will ever appear.

After the source release and public tap have been authorized and published:

```sh
brew tap B03GHB4L1/vizorplay
brew install vizorplay
vizorplay
```

Installing takes several minutes because Homebrew compiles the app (it
installs Rust and Node.js only for the build). `vizorplay` then opens the
VizorPlay window. To also see VizorPlay in Finder's Applications folder, run the
`ln -sfn ...` command that `brew install` prints.

The first launch after installing or upgrading prepares VizorPlay's private
Python environment; the window says "Preparing VizorPlay" meanwhile. It needs
internet access and may take a few minutes. Later launches reuse that
environment. Closing the window stops VizorPlay.

`vizorplay --browser` opens VizorPlay in your default browser instead; keep that
terminal open and press Control-C when finished.

When a newer version is released, the bottom bar shows the update command.
Close VizorPlay, then run:

```sh
brew update
brew upgrade vizorplay
vizorplay
```

Upgrading rebuilds the app, so it takes a few minutes. Projects stay where they
were. `brew uninstall vizorplay` removes the app and leaves your projects.

The tap is currently private and empty. These public installation commands are
preparation instructions, not an announcement that the package is available.

## Scraping and the browser fallback

Most Scoresway and all WhoScored scrapes need no browser. When a Scoresway page
does not list its data links in its HTML, VizorPlay reads it with a browser
already installed on the computer: Microsoft Edge (included with Windows 10 and
11), Google Chrome, Chromium or Brave. Safari and Firefox cannot be used. If none
is installed, that scrape stops with a message asking you to install Edge or
Chrome; nothing is downloaded automatically. Set `VIZORPLAY_BROWSER` to a
browser's full path to choose one.

## Projects and backups

Projects save locally, including match events, kickoff markers, filter settings
and export settings. Video references may point to files elsewhere on your
computer: keep those video files in place. Browser-imported video is copied into
the project. Closing the desktop window stops its engine and active work. With
`vizorplay --browser` on macOS, stop the launcher with Control-C in its terminal;
closing the browser tab alone leaves the launcher running.

Use the local-project picker to see the data-directory location. Before moving
to another computer or making a backup, close the app and copy the data directory
plus any videos stored outside it. Starting a new project does not erase older
projects. Installer acceptance uses disposable projects and never your matches.
