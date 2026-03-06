# MediaKeyControl

Control your Mac's media keys, volume, brightness, and navigate web players from any device on your local network — phone, tablet, or another computer — via a simple web UI. Works as an iPhone home screen app with offline support.

<img src="icon_1024.png" width="96" alt="MediaKeyControl icon">

## Download & Install

Paste this into Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/gupfe-priv-dev/apple-mediakey-control/main/install.sh)"
```

The installer downloads the latest release, installs to `/Applications`, removes the quarantine flag, and launches the app. No Gatekeeper warnings. English and German supported.

## What it does

Opens a password-protected web page (served locally at port 8765) with buttons for:

| Section | Controls |
|---------|----------|
| Media   | F7 Previous · F8 Play/Pause · F9 Next |
| Navigate | Arrow keys ▲▼◀▶ + Enter (D-pad for web players) |
| Volume  | F10 Mute · F11 Down · F12 Up |
| Display (Advanced) | F1 Dim · F2 Brighten |
| System (Advanced) | F3 Mission Control · F4 Launchpad · F5 Kbd Dim · F6 Kbd Brighten |

The UI is responsive — buttons stretch to fill the screen. Tap **Advanced** to show display/system controls. Use **⚙** for settings (connection URLs, password change) and **🔒** to lock.

**Save to iPhone home screen** for a native app experience with offline support — shows a "Server Offline" screen with retry when the Mac is unreachable instead of a browser error.

Use **Show QR Code…** from the menu bar to scan and open the web UI instantly.
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

Volume and mute use AppleScript (`set volume`) and require no special permissions. Brightness, media keys, and navigation (arrow keys/Enter) require Accessibility because they synthesise system-level key events via `CGEventPost`.

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
| 1.1.2 | **Fixes:** Advanced mode layout overlap on iPhone. Accessibility menu now reliably opens System Settings (macOS 13+). Capped button/card height on large screens. Reordered sections: Volume → Media → Navigate. |
| 1.1.1 | Section reorder (Volume → Media → Navigate), capped button/card height on large screens, fixed parent-watchdog crash in standalone mode. |
| 1.1.0 | **D-pad Navigation** — arrow keys ▲▼◀▶ + Enter for web player control (YouTube, Netflix, etc.). **Offline PWA** — save to iPhone home screen; shows "Server Offline" overlay with retry when Mac is unreachable. **Responsive UI** — buttons stretch to fill the screen, no scrolling. **Settings page** — connection URLs and password change via ⚙ icon. **Cleaner layout** — Display/System moved to Advanced; header with SVG icons. |
| 1.0.7 | Universal server binary (arm64 + x86_64), accessibility prompt fallback for macOS 13+ |
| 1.0.6 | **QR Code** — native menu bar panel, scan to open. **Advanced mode** — F3–F6: Mission Control, Launchpad, keyboard brightness. **Bundled server** — no Python required. **Universal binary** — arm64 + x86_64, macOS 10.15+. |
| 1.0.5 | curl-based installer, SVG icons, app icon, favicon, iOS home screen icon |
| 1.0.4 | Release files |
| 1.0.3 | First release |
| 1.0.1 | Remove auto-launch, fix startup thread safety, git-tag versioning |
| 1.0.0 | Initial release — Unix socket IPC, Accessibility prompt, port conflict handling |
