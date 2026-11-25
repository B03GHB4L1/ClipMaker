<p align="center">
  <img src="./ui/assets/brand/vizorplay-lockup.svg" alt="VizorPlay" width="260">
</p>

<h1 align="center">VizorPlay</h1>

<p align="center">Turn a football match video into clips of the moments you care about.</p>

<p align="center">Made by <a href="https://x.com/B03GHB4L1">@B03GHB4L1</a></p>

---

## What it does

Pick a match, choose what you want to see (for example, every pass by one
player, or every shot), and VizorPlay cuts those moments out of your match video
for you.

- **Get the match details automatically.** Paste a link to a match on Scoresway
  or WhoScored and VizorPlay downloads the list of everything that happened in
  it: every pass, shot, tackle and more, with the time it happened. You can
  also use your own spreadsheet file (CSV).
- **Add your match video.** One file for the whole match, or a separate file
  for each half.
- **Choose the moments you want.** Filter by player, team, type of action,
  area of the pitch and more. Watch every clip before you save it, and make any
  clip longer or shorter.
- **Save your clips.** As separate video files, or joined into one highlights
  video.
- **Look deeper.** See shot maps, pass maps and other charts for a match, and
  how a team plays across several matches.
- **See how good each chance was.** VizorPlay xG gives every shot a value from
  0 to 1: the chance it is scored, from where and how it was taken. It shows on
  the shot map, an xG race chart, player comparisons, team style and the Video
  Lab.

Everything stays on your computer and your work is saved as you go.

_VizorPlay used to be called ClipMaker._

### About VizorPlay xG

VizorPlay xG was trained on free match data published by StatsBomb
([StatsBomb open data](https://github.com/statsbomb/open-data)). It looks at
the distance and angle to goal, headers, volleys, free kicks, set pieces, 
counter-attacks, through balls, crosses, one-on-ones and Opta's "big chance" flag. 
The match data doesn't say where defenders and the goalkeeper were, so a 
single shot's value can be off; totals over a match or a season are much steadier.
Penalties count as 0.76; own goals have no xG.

Data: StatsBomb.

---

## Install

> The files below are on the [Releases](../../releases) page. Everything on this
> page is about version 1.0.

Pick your computer below. A [user manual (PDF)](https://b03ghb4l1.github.io/VizorPlay/VizorPlay-User-Manual.pdf) covers every screen.

| Your computer | Download this file | Needs |
|---|---|---|
| Windows 10 or 11 (64-bit) | `VizorPlay_1.0.0_x64-setup.exe` | - |
| Mac with an Apple chip (M1, M2, M3, M4) | `VizorPlay_1.0.0_aarch64.dmg` | macOS 14 (Sonoma) or newer |
| Mac with an Intel chip | `VizorPlay_1.0.0_x64.dmg` | macOS 12 (Monterey) or newer |
| Ubuntu 22.04 or newer, Debian, Linux Mint (64-bit) | `VizorPlay_1.0.0_amd64.deb` | - |

### Windows 10 and 11

1. Download `VizorPlay_1.0.0_x64-setup.exe` from the [Releases](../../releases) page.
2. Close VizorPlay if it is open, then open the file you downloaded. It
   installs for your own account, so you don't need an administrator password.
3. If Windows says "Windows protected your PC", click **More info**, then
   **Run anyway**. This appears because the app isn't registered with
   Microsoft, not because something is wrong.
4. Open **VizorPlay** from the Start menu.

To remove it later: **Settings**, **Apps**, **VizorPlay**, **Uninstall**. Your
projects stay on your computer.

### Mac

**Step 1: find out which kind of Mac you have.** Click the Apple menu in the top
left, then **About This Mac**.

- It says **Chip: Apple M1** (or M2, M3, M4): you have an **Apple Silicon** Mac.
  Download the `aarch64.dmg` file. You need macOS 14 or newer.
- It says **Processor: Intel**: you have an **Intel** Mac. Download the
  `x64.dmg` file. You need macOS 12 or newer.

**Step 2: install.** Open the file you downloaded. A window shows VizorPlay and
your Applications folder. Drag **VizorPlay** onto **Applications**, then eject
the disk (the eject button next to it in the Finder sidebar).

**Step 3: open it the first time.** VizorPlay isn't notarized/signed by Apple,
so your Mac blocks the first launch with a message that it can't verify the app.
You do this once and subsequent launches open normally:

- **macOS 15 (Sequoia) or newer:** open VizorPlay from Applications and close
  the message. Open **System Settings**, then **Privacy & Security**, scroll
  down to **Security**, find "VizorPlay was blocked" and click **Open Anyway**.
  Confirm with your password or Touch ID, then click **Open**.
- **macOS 14 (Sonoma) or older:** in Applications, Control-click (or right-click)
  **VizorPlay**, choose **Open**, then click **Open** again.
- **Still blocked, or it says the app is damaged?** Open **Terminal** and type
  the line below, then open VizorPlay again:

  ```sh
  xattr -dr com.apple.quarantine /Applications/VizorPlay.app
  ```

More details in [docs/INSTALLATION.md](docs/INSTALLATION.md).

To remove/uninstall VizorPlay, drag it from Applications to the Bin.

**Or install with Homebrew**.
If you don't have Homebrew, follow the one-step instructions at
[brew.sh](https://brew.sh) (Apple Silicon only; for an Intel Mac, see the Intel
note below). Then open **Terminal** and type these three lines,
pressing Enter after each one:

```sh
brew tap B03GHB4L1/vizorplay
brew install vizorplay
vizorplay
```

Installing takes a few minutes. The first time VizorPlay opens, it also needs a
few minutes and an internet connection to get ready. After that it opens
straight away: just type `vizorplay` in Terminal. Your Mac may still show a
security message the first time.

**Intel Macs that need Homebrew (including macOS 11).** Since September 2026
the installer on brew.sh only works on Apple Silicon Macs. Homebrew still runs
on Intel Macs with macOS 11 or newer; it just has no official installer for
them. This matters to you if you have an Intel Mac on macOS 11 (the disk image
needs macOS 12). Apple Silicon Macs use the normal brew.sh installer and can skip this.

A community-made, unofficial installer called `homebrew-intel` sets Homebrew up
on Intel Macs. First install Apple's command line tools: open **Terminal**,
type `xcode-select --install` and press Enter. Then paste this one line and
press Enter:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/itsmaclol/homebrew-intel/HEAD/install.sh)"
```

(Its [page](https://github.com/itsmaclol/homebrew-intel) also offers a `.pkg`
installer you can verify.) When it finishes, follow the Homebrew steps above
(`brew tap`, `brew install`, `vizorplay`).

### Linux (Ubuntu 22.04 or newer, Debian, Linux Mint)

1. Download `VizorPlay_1.0.0_amd64.deb` from the [Releases](../../releases) page.
2. Close VizorPlay if it is open. Then double-click the file to install it, or
   open a terminal in your Downloads folder and type:

   ```sh
   sudo apt install ./VizorPlay_1.0.0_amd64.deb
   ```

3. Open **VizorPlay** from your apps menu.

Other Linux types (Fedora, Arch and so on) and ARM computers aren't supported
yet. To remove it later: `sudo apt remove vizorplay`. Your projects stay.

---

## Updating

When a new version comes out, a message appears at the bottom of the app.

- **Windows:** click **Update and restart**. VizorPlay downloads the new
  version, checks it is genuine, closes, updates and opens again by itself. You
  can also just run a newer setup file, but Close VizorPlay before you update manually.
- **Mac (disk image):** click **Update and restart**. VizorPlay downloads the
  new version, checks it is genuine, replaces itself and opens again. If macOS asks
  you to allow the app again, repeat step 3, and if the button reports a problem,
  download the newer `.dmg` for your chip (see the table above), open it,
  drag **VizorPlay** onto **Applications** and choose **Replace**.
- **Mac (Homebrew):** close VizorPlay, then type these three lines in Terminal,
  pressing Enter after each one. It takes a few minutes because it rebuilds the
  app:

  ```sh
  brew update
  brew upgrade vizorplay
  vizorplay
  ```

- **Linux:** click **Update and restart**. VizorPlay downloads the new `.deb`,
  checks it is genuine, then asks for your password in the usual system window
  and installs it. If you cancel that window, nothing changes and VizorPlay keeps
  running. If no password window can open, download the newer `.deb` from the
  Releases page and install it with the same command as before.

---

## Version history

### VizorPlay 1.0

- A brand-new app for Windows, Mac and Linux, under a new name
- Smaller download, and it updates itself on Windows, Linux and the Mac disk-image app
- Much faster video saving on computers with an NVIDIA graphics card
- VizorPlay xG: how good every chance was, on the shot map, an xG race and more
- Your projects are saved and reopen exactly as you left them
- The AI filter from older versions has been removed

### Older versions (as ClipMaker)

- **1.2.3:** match details from Scoresway, save charts as pictures or
  animations, support for extra time and penalty shootouts
- **1.2.2:** see how a team plays across matches, highlights of several players
  at once, get several matches at once
- **1.2.1:** pressing chart, trim clips while watching them, faster previews
- **1.2:** match details from WhoScored, match charts, saved filters
- **1.1:** more ways to filter, support for videos split into halves
- **1.0:** first version

The source of these older apps (the separate Windows, Linux and Mac versions of ClipMaker 1.2.3) is kept on the [`archive/clipmaker-1.2.3`](https://github.com/B03GHB4L1/VizorPlay/tree/archive/clipmaker-1.2.3) branch.

## Licence

VizorPlay is source-available, not open source. It is free for noncommercial
use: personal study, hobby and amateur analysis, charities, schools, public
research and government. The licence, the
[PolyForm Strict License 1.0.0](LICENSE), does not allow changing VizorPlay or
sharing copies of it.

Professional clubs, paid analysts and coaching businesses need a commercial
licence: email [granvskaia@gmail.com](mailto:granvskaia@gmail.com).

ClipMaker, the app VizorPlay replaces, was released under the MIT License, and
that still applies to every ClipMaker release
([LICENSE-MIT-EARLIER.md](LICENSE-MIT-EARLIER.md)).

---

<p align="center">VizorPlay by B4L1 · <a href="https://x.com/B03GHB4L1">@B03GHB4L1</a></p>
