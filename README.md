# MediaKeyControl

Control your Mac's media and brightness keys from any device on your local network — phone, tablet, or another computer — via a simple web UI in the browser.

<img src="icon_1024.png" width="96" alt="MediaKeyControl icon">

## Download & Install

Paste this into Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/gupfe-priv-dev/apple-mediakey-control/main/install.sh)"
```

The installer downloads the latest release, installs to `/Applications`, removes the quarantine flag, and launches the app. No Gatekeeper warnings. English and German supported.

## What it does

Opens a password-protected web page (served locally at port 8765) with buttons for:

| Section | Keys |
|---------|------|
| Display | F1 Dim · F2 Brighten |
| Media   | F7 Previous · F8 Play/Pause · F9 Next |
| Volume  | F10 Mute · F11 Down · F12 Up |
| System (Advanced) | F3 Mission Control · F4 Launchpad · F5 Kbd Dim · F6 Kbd Brighten |

Tap **Advanced** in the web UI to show the System row. Use **Show QR Code…** from the menu bar to open a native QR code panel — scan with your phone to open the web UI instantly.

Add it to your iPhone home screen as a web app for quick access.
Works with MacBook, iMac, or any Mac — with any keyboard attached.

## First run

1. **Set a password** — the web UI will prompt on first visit.
2. **Grant Accessibility** — macOS will open System Settings automatically. Toggle MediaKeyControl on in the Accessibility list. This is required for brightness and media key simulation.

> The Accessibility grant is tied to the app's path in `/Applications`. It persists across updates as long as the app stays there. Use **"Grant Accessibility…"** from the menu bar icon if you ever need to re-grant.

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

## Build from source

Requires macOS 10.15+ (Catalina on Intel, Big Sur on Apple Silicon), Xcode Command Line Tools and Python 3.

```bash
./build.sh                          # compile MediaKeyControl.app
cp -r MediaKeyControl.app /Applications/
xattr -dr com.apple.quarantine /Applications/MediaKeyControl.app
open /Applications/MediaKeyControl.app
```

## Standalone mode

You can run the server without the app (e.g. for development):

```bash
python3 server.py
```

In this mode, key events fall back to a compiled Swift binary (`mediakey`). Grant Accessibility to Terminal for this to work.

## Version history

| Version | Notes |
|---------|-------|
| 1.0.6 | **QR Code** — native menu bar panel (no dependencies), scan to open on any device. **Advanced mode** — F3–F6 keys: Mission Control, Launchpad, keyboard brightness. **Bundled server** — no Python required on target machine. **Universal binary** — arm64 + x86_64, macOS 10.15+. **Fixes** — play/pause icon, Accessibility TCC identity persists across updates. |
| 0.0.1 | **QR Code** — native menu bar panel (no dependencies), scan to open on any device. **Advanced mode** — F3–F6 keys: Mission Control, Launchpad, keyboard brightness. **Bundled server** — no Python required on target machine. **Universal binary** — arm64 + x86_64, macOS 10.15+. **Fixes** — play/pause icon, Accessibility TCC identity persists across updates. |
| 0.0.1 | **QR Code** — native menu bar panel (no dependencies), scan to open on any device. **Advanced mode** — F3–F6 keys: Mission Control, Launchpad, keyboard brightness. **Bundled server** — no Python required on target machine. **Universal binary** — arm64 + x86_64, macOS 10.15+. **Fixes** — play/pause icon, Accessibility TCC identity persists across updates. |
| 1.0.5 | curl-based installer, SVG icons, app icon, favicon, iOS home screen icon |
| 1.0.4 | added: release files |
| 1.0.3 | First Release |
| 1.0.1 | Remove auto-launch, fix startup thread safety, git-tag versioning |
| 1.0.0 | Initial release — Unix socket IPC, Accessibility prompt, port conflict handling |
