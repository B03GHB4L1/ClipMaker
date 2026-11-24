# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Plain static HTML/CSS/JS in `site/`, no build step, deployable with GitHub Pages. (Chosen by the user.)

## Users

Football analysts, coaches and fans who have a match video and want clips of specific moments (one player's passes, every shot) without cutting by hand. The landing page is for visitors deciding whether to download VizorPlay and which file to get. The user asked for an industry-standard landing page.

## Product Purpose

VizorPlay turns a football match video into clips of chosen moments. It downloads the match event list (Scoresway, WhoScored, or a CSV), lines it up with the video, filters by player, team, action and pitch area, previews and trims every clip, and exports separate clips or one highlights video. It also shows shot maps, pass maps, team style charts and VizorPlay xG.

## Positioning

Everything runs on the user's own computer: no account, no upload, nothing else to install (no Python, no FFmpeg). Projects save locally and are never overwritten.

## Operating Context

Desktop app for Windows 10/11, macOS (Apple chip, macOS 14+; Intel, macOS 12+) and Ubuntu/Debian Linux. Installers are unsigned, so Windows SmartScreen and macOS Gatekeeper warnings need an honest, plain walkthrough.

## Capabilities and Constraints

- Version 1.0 is not released yet; download buttons must say so and link to Releases.
- Windows updates in-app; Mac and Linux update by installing the newer file.
- Licence: PolyForm Strict 1.0.0 plus separate commercial licences (contact granvskaia@gmail.com); earlier ClipMaker code is MIT.
- AI filtering is excluded from scope.
- VizorPlay xG trained on StatsBomb open data (attribution required: "Data: StatsBomb").

## Brand Commitments

Name VizorPlay (formerly ClipMaker). Logo: glasses with a green play nose (`ui/assets/brand/`), ink #161616, green #1C9938. The app uses Geist Mono. Version shown as 1.0.

## Evidence on Hand

Product screenshots and the chrome football render exist in `ui/assets/`. No testimonials, customers, download counts or press: none may be invented.

## Product Principles

1. Be plain: say what happens, and where it goes wrong.
2. Local and private by default.
3. Honest about unsigned installers and the unreleased version.
4. Show the real product, not stock imagery.

## Accessibility & Inclusion

Keyboard navigable, readable at phone width, respects reduced motion.
