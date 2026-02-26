# MediaKeyControl

Control your MacBook's media and brightness keys from any device on your local network — phone, tablet, or another computer — via a simple web UI in the browser.

![UI showing Display, Media, and Volume controls]

## What it does

Opens a password-protected web page (served locally at port 8765) with buttons for:

| Section | Keys |
|---------|------|
| Display | F1 Dim · F2 Brighten |
| Media   | F7 Previous · F8 Play/Pause · F9 Next |
| Volume  | F10 Mute · F11 Down · F12 Up |

Add it to your iPhone home screen as a web app for quick access.

## Requirements

- macOS 12 or later
- Xcode Command Line Tools (`xcode-select --install`)
- Python 3 (ships with macOS or via Homebrew)

## Download

Grab the latest `MediaKeyControl.zip` from the [Releases](https://github.com/gupfe-priv-dev/apple-mediakey-control/releases/latest) page, unzip, and move the app to `/Applications`.

Since the app is unsigned, macOS will block it on first launch. If you use `install.sh` it handles this automatically. Otherwise remove the quarantine flag once manually:

```bash
xattr -dr com.apple.quarantine /Applications/MediaKeyControl.app
```

## Build & Install

```bash
./build.sh      # compiles MediaKeyControl.app in the project directory
./install.sh    # copies it to /Applications (auto-builds if needed)
```

Then launch:

```bash
open /Applications/MediaKeyControl.app
```

## First run

1. **Set a password** — the web UI will prompt on first visit.
2. **Grant Accessibility** — macOS will open System Settings automatically. Toggle MediaKeyControl on in the Accessibility list. This is required for brightness and media key simulation.

> After every rebuild the binary changes, so macOS revokes the Accessibility entry. Use **"Grant Accessibility…"** from the menu bar icon to re-open the Settings pane quickly.

## Usage

- The app lives in the menu bar (keyboard icon).
- Open the web UI from the menu or bookmark `http://<your-mac>.local:8765` on any device.
- The Bonjour hostname (`.local`) is shown in the menu and on the web page — use it for a stable bookmark that doesn't change when your IP does.

## How it works

```
Browser (iOS/other device)
  → HTTP POST /action
    → Python server (server.py, port 8765)
      → Unix socket (/tmp/mediakeycontrol.sock)
        → MediaKeyControl.app (trusted process)
          → CGEventPost (NX key events)
```

Volume and mute use AppleScript (`set volume`) and require no special permissions. Brightness and media keys require Accessibility because they synthesise system-level key events via `CGEventPost`.

## Standalone mode

You can run the server without the app (e.g. for development):

```bash
python3 server.py
```

In this mode, key events fall back to a compiled Swift binary (`mediakey`). Grant Accessibility to Terminal for this to work.

## Version history

| Version | Notes |
|---------|-------|
| 1.0.3 | First Release |
| 1.0.1 | Remove auto-launch, fix startup thread safety, git-tag versioning |
| 1.0.0 | Initial release — Unix socket IPC, Accessibility prompt, port conflict handling |
