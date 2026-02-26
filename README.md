# MediaKeyControl

Control your Mac's media and brightness keys from any device on your local network — phone, tablet, or another computer — via a simple web UI in the browser.

![App icon and web UI](icon_1024.png)

## What it does

Opens a password-protected web page (served locally at port 8765) with buttons for:

| Section | Keys |
|---------|------|
| Display | F1 Dim · F2 Brighten |
| Media   | F7 Previous · F8 Play/Pause · F9 Next |
| Volume  | F10 Mute · F11 Down · F12 Up |

Add it to your iPhone home screen as a web app for quick access.
Works with MacBook, iMac, or any Mac — with any keyboard attached.

## Requirements

- macOS 12 or later
- Xcode Command Line Tools (`xcode-select --install`)
- Python 3 (ships with macOS or via Homebrew)

## Download & Install

Grab the latest `MediaKeyControl.zip` from the [Releases](https://github.com/gupfe-priv-dev/apple-mediakey-control/releases/latest) page, unzip it, then double-click **`Install MediaKeyControl.command`**.

The installer:
- Asks before touching anything (Y/N prompt)
- Copies the app to `/Applications` and removes the quarantine flag automatically
- Opens a summary text file with the web UI URL
- Detects your system language (English / German)
- Self-closes the Terminal window when done

## Build from source

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
- Login sessions persist across server restarts (30-day cookie).

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
| 1.0.4 | added: release files |
| 1.0.3 | First Release |
| 1.0.1 | Remove auto-launch, fix startup thread safety, git-tag versioning |
| 1.0.0 | Initial release — Unix socket IPC, Accessibility prompt, port conflict handling |
