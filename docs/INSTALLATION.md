# Install and update VizorPlay 1.0

These instructions describe the prepared 1.0 distribution. A candidate artifact
is available only after its Actions run passes; a public release and package
channels must be published separately before their public commands work.

## Windows x64

1. Download the VizorPlay setup `.exe` from the official GitHub release.
2. Close an older VizorPlay window, if open.
3. Run the installer and follow its prompts. It installs for your user account.
4. Open VizorPlay from the Start menu.

For an update, download and run the newer setup file. Keep the same installation
location. Saved projects are stored separately from the installed program.
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

For an update, close VizorPlay and install the newer DEB with the same command.
APT installs required system dependencies. This is a downloaded package; an
automatic APT update repository is not currently configured. Other distributions
and RPM packages are outside the verified candidate scope.

## macOS Homebrew

The shared app opens in your default browser on macOS. No Apple Developer
membership is required for this source-launcher route. It does not promise that
every macOS security warning disappears or disable Gatekeeper.

After the source release and public tap have been authorized and published:

```sh
brew tap B03GHB4L1/clipmaker
brew install clipmaker
vizorplay
```

Keep the terminal open while using the app. The first launch downloads its
private Python environment, dependencies and scraper browser; it needs internet
access and may take several minutes. Later launches reuse that environment.
Press Control-C in the terminal when finished.

For an update, close VizorPlay, then run:

```sh
brew update
brew upgrade clipmaker
vizorplay
```

The tap is currently private and empty. These public installation commands are
preparation instructions, not an announcement that the package is available.

## Projects and backups

Projects save locally, including match events, kickoff markers, filter settings
and export settings. Video references may point to files elsewhere on your
computer: keep those video files in place. Browser-imported video is copied into
the project. Closing the Windows/Linux desktop window stops its engine and
active work. On macOS, stop the launcher with Control-C in its terminal;
closing the browser tab alone leaves the launcher running.

Use the local-project picker to see the data-directory location. Before moving
to another computer or making a backup, close the app and copy the data directory
plus any videos stored outside it. Starting a new project does not erase older
projects. Installer acceptance uses disposable projects and never your matches.
