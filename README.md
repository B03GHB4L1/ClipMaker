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

Everything stays on your computer. Your work is saved as you go, and starting
a new project never deletes an old one.

VizorPlay used to be called ClipMaker.

### About VizorPlay xG

VizorPlay xG was trained on free match data published by StatsBomb
([StatsBomb open data](https://github.com/statsbomb/open-data)). Only the
finished model ships with the app, so nothing is downloaded and your matches
never leave your computer. It looks at the distance and angle to goal, headers,
volleys, free kicks, set pieces, counter-attacks, through balls, crosses,
one-on-ones and Opta's "big chance" flag. The match data doesn't say where
defenders and the goalkeeper were, so a single shot's value can be off; totals
over a match or a season are much steadier. Penalties count as 0.76; own goals
have no xG.

Data: StatsBomb.

---

## Install

> Version 1.0 is not out yet. When it is, the files below will be on the
> [Releases](../../releases) page.

### Windows 10 and 11

1. Download `VizorPlay_1.0.0_x64-setup.exe` from the [Releases](../../releases) page.
2. Open it to install VizorPlay.
3. If Windows says "Windows protected your PC", click **More info**, then
   **Run anyway**. This appears because the app isn't registered with
   Microsoft, not because something is wrong.

### Mac

1. Check your Mac's chip: Apple menu, **About This Mac**. *Chip: Apple M…*
   means Apple Silicon; *Processor: Intel* means Intel.
2. Download `VizorPlay_1.0.0_aarch64.dmg` (Apple Silicon) or
   `VizorPlay_1.0.0_x64.dmg` (Intel) from the [Releases](../../releases) page.
   The Intel file is still being tested; until it is there, use Homebrew below.
3. Open the file and drag **VizorPlay** onto **Applications**.
4. Open VizorPlay from Applications. VizorPlay isn't approved by Apple, so your
   Mac blocks it the first time. On macOS 15 or later, open **System Settings**,
   **Privacy & Security**, and click **Open Anyway**. On macOS 14 or earlier,
   Control-click VizorPlay in Applications and choose **Open**. You only do this
   once.

Step-by-step help, including a Terminal option, is in
[docs/INSTALLATION.md](docs/INSTALLATION.md).

**Or, with Homebrew** (slower, because it builds the app on your Mac): if you
don't have it, follow the one-step instructions at [brew.sh](https://brew.sh).
Then open the **Terminal** app and type these three lines, pressing Enter after
each one:

```sh
brew tap B03GHB4L1/vizorplay
brew install vizorplay
vizorplay
```

Installing takes a few minutes. The first time VizorPlay opens, it also needs a
few minutes and an internet connection to get ready. After that it opens
straight away: just type `vizorplay` in Terminal.

VizorPlay isn't approved by Apple, so it's possible your Mac shows a security
message when you open it.

### Linux (Ubuntu, Debian, Linux Mint)

1. Download `VizorPlay_1.0.0_amd64.deb` from the [Releases](../../releases) page.
2. Double-click it to install it. Or open a terminal in your Downloads folder
   and type `sudo apt install ./VizorPlay_1.0.0_amd64.deb`.
3. Open **VizorPlay** from your apps menu.

---

## Updating

You only install VizorPlay once. When a new version comes out, a message
appears at the bottom of the app:

- **Windows:** click **Update and restart**. That's it.
- **Mac:** download the newer disk image and drag VizorPlay onto Applications
  again (choose **Replace**). If you used Homebrew, close VizorPlay, then type
  `brew upgrade vizorplay` in Terminal.
- **Linux:** click **Download**, then install the new file the same way as
  before.

Updating never deletes your projects.

---

## Version history

### VizorPlay 1.0 (coming soon)

- A brand-new app for Windows, Mac and Linux, under a new name
- Smaller download, and it updates itself on Windows
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

---

<p align="center">VizorPlay by B4L1 · <a href="https://x.com/B03GHB4L1">@B03GHB4L1</a></p>
