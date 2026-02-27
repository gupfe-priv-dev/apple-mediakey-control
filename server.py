#!/usr/bin/env python3
"""
apple-mediakey-control — server.py
Web server component. Normally launched by MediaKeyControl.app.
Can also be run standalone: python3 server.py [port]

Password is stored in:
  ~/Library/Application Support/MediaKeyControl/settings.plist
Change it: python3 server.py --set-password <newpassword>
"""

import base64
import http.server
import os
import json
import plistlib
import secrets as _sec
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8765
# When frozen by PyInstaller (--onefile), sys.executable is the binary path.
# In that case __file__ is inside a temp extraction dir and siblings like
# `mediakey` live next to the binary — use sys.executable's parent instead.
BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent

# ── Swift NX-key helper ────────────────────────────────────────────────────────

_SWIFT_SRC = """\
import Cocoa
let args = CommandLine.arguments
guard args.count > 1, let key = Int(args[1]) else { exit(1) }
func send(_ key: Int) {
    let t = ProcessInfo.processInfo.systemUptime
    let dn = NSEvent.otherEvent(with: .systemDefined,
        location: NSPoint(x: 0, y: 0),
        modifierFlags: NSEvent.ModifierFlags(rawValue: 0xa00),
        timestamp: t, windowNumber: 0, context: nil, subtype: 8,
        data1: (key << 16) | (0xa << 8), data2: -1)
    let up = NSEvent.otherEvent(with: .systemDefined,
        location: NSPoint(x: 0, y: 0),
        modifierFlags: NSEvent.ModifierFlags(rawValue: 0xb00),
        timestamp: t, windowNumber: 0, context: nil, subtype: 8,
        data1: (key << 16) | (0xb << 8), data2: -1)
    dn?.cgEvent?.post(tap: .cgSessionEventTap)
    Thread.sleep(forTimeInterval: 0.02)
    up?.cgEvent?.post(tap: .cgSessionEventTap)
}
send(key)
"""

_BIN = BASE / "mediakey"
_swift_ok = False

def _setup_swift():
    global _swift_ok
    if _BIN.exists():                     # pre-compiled (inside .app bundle)
        _swift_ok = True
        return
    src = BASE / "mediakey.swift"         # standalone: compile from source
    src.write_text(_SWIFT_SRC)
    r = subprocess.run(["swiftc", str(src), "-o", str(_BIN)], capture_output=True)
    _swift_ok = r.returncode == 0
    if not _swift_ok:
        print("  ⚠  swiftc not found — install Xcode Command Line Tools:")
        print("     xcode-select --install")
        if r.stderr:
            print(f"     {r.stderr.decode().strip()}")

def _check_accessibility() -> bool:
    import ctypes
    try:
        ax = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        return bool(ax.AXIsProcessTrusted())
    except Exception:
        return False

# NX key type constants (IOKit/hidsystem/ev_keymap.h)
_NX_SOUND_UP    = 0
_NX_SOUND_DOWN  = 1
_NX_BRIGHT_UP   = 2
_NX_BRIGHT_DOWN = 3
_NX_MUTE        = 7
_NX_PLAY        = 16
_NX_NEXT        = 17
_NX_PREV        = 18
_NX_KBD_UP      = 21
_NX_KBD_DOWN    = 22

_SOCK_PATH = "/tmp/mediakeycontrol.sock"

def _nx(key: int):
    # App mode: send via Unix socket to MediaKeyControl.app (trusted process)
    try:
        import socket as _socket
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(0.5)
        sock.connect(_SOCK_PATH)
        sock.send(str(key).encode())
        sock.close()
        return
    except Exception:
        pass
    # Standalone fallback: direct binary
    if _swift_ok:
        subprocess.Popen([str(_BIN), str(key)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _osa(s: str):
    subprocess.Popen(["osascript", "-e", s],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _vol_up():
    _osa("set volume output volume ((output volume of (get volume settings)) + 6.25)")

def _vol_down():
    _osa("set volume output volume ((output volume of (get volume settings)) - 6.25)")

def _mute_toggle():
    _osa("set volume output muted (not output muted of (get volume settings))")

def _open_app(name: str):
    subprocess.Popen(["open", "-a", name],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

_ACTIONS = {
    # AppleScript — no Accessibility needed
    "volume_up":         _vol_up,
    "volume_down":       _vol_down,
    "mute":              _mute_toggle,
    # NX key events — need Accessibility permission
    "brightness_down":   lambda: _nx(_NX_BRIGHT_DOWN),
    "brightness_up":     lambda: _nx(_NX_BRIGHT_UP),
    "prev_track":        lambda: _nx(_NX_PREV),
    "play_pause":        lambda: _nx(_NX_PLAY),
    "next_track":        lambda: _nx(_NX_NEXT),
    # Advanced — keyboard brightness (NX, needs Accessibility)
    "kbd_bright_up":     lambda: _nx(_NX_KBD_UP),
    "kbd_bright_down":   lambda: _nx(_NX_KBD_DOWN),
    # Advanced — system (Launch Services, no special permissions)
    "mission_control":   lambda: _open_app("Mission Control"),
    "launchpad":         lambda: _open_app("Launchpad"),
}

def _get_status():
    vol = subprocess.run(
        ["osascript", "-e", "output volume of (get volume settings)"],
        capture_output=True, text=True, timeout=2)
    mut = subprocess.run(
        ["osascript", "-e", "output muted of (get volume settings)"],
        capture_output=True, text=True, timeout=2)
    try:    volume = int(vol.stdout.strip())
    except: volume = -1
    muted = mut.stdout.strip() == "true"
    return {"volume": volume, "muted": muted}

# ── Password / settings (Application Support plist) ───────────────────────────

APP_SUPPORT  = Path.home() / "Library" / "Application Support" / "MediaKeyControl"
SETTINGS_FILE = APP_SUPPORT / "settings.plist"
COOKIE_NAME  = "mk_session"
SESSION_TTL  = 30 * 24 * 3600   # 30 days

_sessions: dict = {}
_password: str  = ""            # empty = not configured yet

def _load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "rb") as f:
                return plistlib.load(f)
    except Exception:
        pass
    return {}

def _save_settings(data: dict):
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "wb") as f:
        plistlib.dump(data, f)

def _save_password(pw: str):
    global _password
    _password = pw
    s = _load_settings()
    s["password_b64"] = base64.b64encode(pw.encode()).decode()
    _save_settings(s)

def _load_sessions_from_disk() -> dict:
    s = _load_settings()
    now = time.time()
    return {k: v for k, v in s.get("sessions", {}).items() if v > now}

def _save_sessions_to_disk():
    s = _load_settings()
    now = time.time()
    s["sessions"] = {k: v for k, v in _sessions.items() if v > now}
    _save_settings(s)

def _setup_auth():
    global _password, _sessions
    s   = _load_settings()
    b64 = s.get("password_b64", "")
    if b64:
        try:
            _password = base64.b64decode(b64.encode()).decode()
            print("  ✓  Password loaded from Application Support")
        except Exception:
            _password = ""
    else:
        _password = ""
        print("  ℹ  No password set — first-run setup via web UI")
    _sessions = _load_sessions_from_disk()
    if _sessions:
        print(f"  ✓  Restored {len(_sessions)} active session(s)")

def _valid_session(token: str) -> bool:
    exp = _sessions.get(token)
    if not exp:
        return False
    if time.time() > exp:
        _sessions.pop(token, None)
        return False
    _sessions[token] = time.time() + SESSION_TTL
    return True

def _new_session() -> str:
    token = _sec.token_hex(32)
    _sessions[token] = time.time() + SESSION_TTL
    _save_sessions_to_disk()
    return token

def _get_cookie(handler, name: str) -> str:
    for part in handler.headers.get("Cookie", "").split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            return part[len(name) + 1:]
    return ""

def _is_authed(handler) -> bool:
    return _valid_session(_get_cookie(handler, COOKIE_NAME))

def _cookie_set(token: str, max_age: int = SESSION_TTL) -> str:
    return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"

def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def _bonjour_host() -> str:
    """Return Bonjour/mDNS hostname (e.g. Gunnars-MBP.local). Called once at startup."""
    try:
        r = subprocess.run(["scutil", "--get", "LocalHostName"],
                           capture_output=True, text=True, timeout=2)
        name = r.stdout.strip()
        if r.returncode == 0 and name:
            return f"{name}.local"
    except Exception:
        pass
    h = socket.gethostname()
    return h if h.endswith(".local") else f"{h}.local"

# Resolved once at startup — never called during request handling
_SERVER_HOST = ""
_SERVER_IP   = ""
_BM_URL      = ""   # e.g. http://Gunnars-MBP.local:8765
_IP_URL      = ""   # e.g. http://192.168.1.42:8765

# ── HTML templates ─────────────────────────────────────────────────────────────

_COMMON_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; background: #000; font-family: -apple-system, BlinkMacSystemFont, sans-serif; color: #fff; }
body { display: flex; align-items: center; justify-content: center; padding: 24px; min-height: 100dvh; }
.card {
  background: rgba(28,28,30,.98); border-radius: 22px; padding: 36px 24px 28px;
  width: 100%; max-width: 320px; display: flex; flex-direction: column; align-items: center; gap: 18px;
}
.icon  { font-size: 52px; line-height: 1; }
.title { font-size: 20px; font-weight: 700; letter-spacing: -.4px; }
.hint  { font-size: 14px; color: rgba(235,235,245,.55); text-align: center; line-height: 1.4; }
form   { width: 100%; display: flex; flex-direction: column; gap: 10px; }
input[type=password], input[type=text] {
  width: 100%; background: rgba(58,58,60,.9); border: none; border-radius: 12px;
  color: #fff; font-family: inherit; font-size: 17px; padding: 14px 16px; outline: none; -webkit-appearance: none;
}
input::placeholder { color: rgba(235,235,245,.3); }
input:focus { background: rgba(78,78,80,.95); }
.btn {
  width: 100%; background: #0a84ff; border: none; border-radius: 12px;
  color: #fff; font-family: inherit; font-size: 17px; font-weight: 600;
  padding: 14px; cursor: pointer; -webkit-tap-highlight-color: transparent;
  touch-action: manipulation; transition: opacity .15s;
}
.btn:active { opacity: .75; }
.btn-ghost {
  width: 100%; background: rgba(58,58,60,.6); border: none; border-radius: 12px;
  color: rgba(235,235,245,.7); font-family: inherit; font-size: 15px;
  padding: 12px; cursor: pointer; -webkit-tap-highlight-color: transparent;
  touch-action: manipulation; text-decoration: none; display: block; text-align: center;
}
.error   { font-size: 13px; color: #ff453a; text-align: center; }
.success { font-size: 13px; color: #30d158; text-align: center; }
"""

# ── Embedded icon assets (favicon 32px, touch-icon 180px) ────────────────────
_FAVICON_PNG    = base64.b64decode("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")
_TOUCH_ICON_PNG = base64.b64decode("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")

_META = """<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">"""

_COMMON_EXTRA_CSS = """
.bm-note { display:flex; flex-direction:column; align-items:center; gap:4px; width:100%; }
.bm-label { font-size: 11px; color: rgba(235,235,245,.3); }
.bm-link  { font-size: 13px; color: rgba(10,132,255,.6); text-decoration: none; word-break: break-all; text-align: center; }
"""

_SETUP_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>{_META}
<meta name="apple-mobile-web-app-title" content="MediaKeys">
<meta name="theme-color" content="#000000">
<link rel="manifest" href="/manifest.json">
<title>MediaKeyControl — Setup</title>
<style>{_COMMON_CSS}{_COMMON_EXTRA_CSS}</style>
</head>
<body>
<div class="card">
  <span class="icon">⌨️</span>
  <div style="display:flex;flex-direction:column;align-items:center;gap:6px">
    <span class="title">Welcome</span>
    <span class="hint">Choose a password to protect<br>your MacBook controls</span>
  </div>
  __ERROR__
  <form method="POST" action="/setup">
    <input type="password" name="pw"  placeholder="Password"         required minlength="4" autofocus autocomplete="new-password">
    <input type="password" name="pw2" placeholder="Confirm password" required minlength="4" autocomplete="new-password">
    <button class="btn" type="submit">Set Password</button>
  </form>
  <div class="bm-note">
    <span class="bm-label">Save this URL as a bookmark or Home Screen app:</span>
    <a class="bm-link" href="__BOOKMARK_URL__">__BOOKMARK_URL__</a>
  </div>
</div>
<script>document.querySelector('input').focus();</script>
</body>
</html>"""

_LOGIN_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>{_META}
<meta name="apple-mobile-web-app-title" content="MediaKeys">
<meta name="theme-color" content="#000000">
<link rel="manifest" href="/manifest.json">
<title>MediaKeyControl</title>
<style>{_COMMON_CSS}{_COMMON_EXTRA_CSS}</style>
</head>
<body>
<div class="card">
  <span class="icon">⌨️</span>
  <div style="display:flex;flex-direction:column;align-items:center;gap:6px">
    <span class="title">MacBook Controls</span>
    <span class="hint">Enter password to continue</span>
  </div>
  __ERROR__
  <form method="POST" action="/login">
    <input type="text" name="username" autocomplete="username" value="admin" tabindex="-1" aria-hidden="true" style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0">
    <input type="password" name="pw" id="password" placeholder="Password" autofocus autocomplete="current-password">
    <button class="btn" type="submit">Unlock</button>
  </form>
  <div class="bm-note">
    <span class="bm-label">Bookmark URL (stable, works on your local network):</span>
    <a class="bm-link" href="__BOOKMARK_URL__">__BOOKMARK_URL__</a>
  </div>
</div>
<script>document.querySelector('input').focus();</script>
</body>
</html>"""

_CHANGE_PW_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>{_META}
<title>MediaKeyControl — Change Password</title>
<style>{_COMMON_CSS}
.back {{ font-size: 14px; color: rgba(10,132,255,.9); text-decoration: none; align-self: flex-start; }}
</style>
</head>
<body>
<div class="card">
  <a class="back" href="/">← Back</a>
  <span class="title">Change Password</span>
  __MSG__
  <form method="POST" action="/change-password">
    <input type="password" name="cur" placeholder="Current password"  required autofocus autocomplete="current-password">
    <input type="password" name="pw"  placeholder="New password"      required minlength="4" autocomplete="new-password">
    <input type="password" name="pw2" placeholder="Confirm new password" required minlength="4" autocomplete="new-password">
    <button class="btn" type="submit">Update Password</button>
  </form>
</div>
<script>document.querySelector('input').focus();</script>
</body>
</html>"""

_MAIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<link rel="icon" href="/favicon.ico">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="apple-mobile-web-app-title" content="MediaKeys">
<meta name="theme-color" content="#000000">
<link rel="manifest" href="/manifest.json">
<title>MacBook Controls</title>
<style>
:root {
  --bg:     #000; --card: rgba(28,28,30,.98); --btn: rgba(58,58,60,.9);
  --btn-on: rgba(99,99,102,1); --text: #fff; --dim: rgba(235,235,245,.48);
  --r-card: 20px; --r-btn: 14px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { background: var(--bg); }
body {
  background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif;
  min-height: 100dvh;
  padding: max(env(safe-area-inset-top),20px) 16px max(env(safe-area-inset-bottom),24px);
  display: flex; flex-direction: column; gap: 10px;
  max-width: 430px; margin: 0 auto;
}
header { padding: 4px 4px 2px; }
.hrow { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
header h1 { font-size: 22px; font-weight: 700; letter-spacing: -.5px; }
.hlinks { display: flex; gap: 2px; }
.hlink {
  font-size: 13px; color: rgba(10,132,255,.9); text-decoration: none;
  font-weight: 500; padding: 4px 8px; border-radius: 8px;
  -webkit-tap-highlight-color: transparent;
}
.hlink:active { background: rgba(10,132,255,.15); }
.vol-row { display: flex; align-items: center; gap: 8px; }
#vol-pct { font-size: 13px; font-weight: 600; color: var(--dim); min-width: 36px; text-align: right; }
.vol-track { flex: 1; background: rgba(255,255,255,.12); border-radius: 99px; height: 5px; overflow: hidden; }
#vol-fill { height: 100%; background: #fff; border-radius: 99px; width: 50%; transition: width .35s ease, background .3s; }
#vol-fill.muted { background: rgba(255,255,255,.28); }
.card { background: var(--card); border-radius: var(--r-card); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.card-label { font-size: 11px; font-weight: 600; letter-spacing: .8px; text-transform: uppercase; color: var(--dim); }
.row { display: grid; gap: 8px; }
.row-2 { grid-template-columns: 1fr 1fr; }
.row-3 { grid-template-columns: 1fr 2fr 1fr; }
button {
  all: unset; background: var(--btn); border-radius: var(--r-btn); cursor: pointer;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 6px; padding: 18px 8px; min-height: 84px; text-align: center;
  -webkit-tap-highlight-color: transparent; touch-action: manipulation;
  transition: background 80ms ease, transform 80ms ease;
  user-select: none; -webkit-user-select: none; will-change: transform;
}
button:active, button.tap { background: var(--btn-on); transform: scale(0.92); }
.icon { width: 30px; height: 30px; display: block; pointer-events: none; }
.sub  { font-size: 11px; color: var(--dim); line-height: 1.3; pointer-events: none; }
.c-display button            { background: rgba(255,159,10,.15); }
.c-display button:active,
.c-display button.tap        { background: rgba(255,159,10,.42); }
.c-system button             { background: rgba(191,90,242,.15); }
.c-system button:active,
.c-system button.tap         { background: rgba(191,90,242,.42); }
.c-kbd button                { background: rgba(10,132,255,.13); }
.c-kbd button:active,
.c-kbd button.tap            { background: rgba(10,132,255,.35); }
.c-media button              { background: rgba(48,209,88,.13); }
.c-media button:active,
.c-media button.tap          { background: rgba(48,209,88,.35); }
.c-media .play               { background: rgba(48,209,88,.26); }
.c-media .play:active,
.c-media .play.tap           { background: rgba(48,209,88,.52); }
.c-vol button                { background: rgba(255,69,58,.13); }
.c-vol button:active,
.c-vol button.tap            { background: rgba(255,69,58,.35); }
.c-adv button                { background: rgba(100,210,255,.12); }
.c-adv button:active,
.c-adv button.tap            { background: rgba(100,210,255,.35); }
.adv-hidden { display: none; }
footer { text-align: center; padding: 8px 4px 4px; display: flex; flex-direction: column; gap: 3px; }
.bm-label { font-size: 11px; color: rgba(235,235,245,.2); }
.bm-link  { font-size: 13px; color: rgba(10,132,255,.45); text-decoration: none; word-break: break-all; }

/* ── Compact layout for small screens (iPhone SE / 8) ── */
@media (max-height: 650px) {
  body   { gap: 7px; padding-top: max(env(safe-area-inset-top),12px); padding-bottom: max(env(safe-area-inset-bottom),14px); }
  header h1 { font-size: 18px; }
  .hrow  { margin-bottom: 7px; }
  .card  { padding: 10px; gap: 7px; }
  .row   { gap: 6px; }
  button { padding: 11px 6px; min-height: 68px; gap: 3px; }
  .icon  { width: 26px; height: 26px; }
  .sub   { font-size: 10px; }
  footer { padding: 4px 4px 2px; }
  .bm-label { display: none; }
  .bm-link  { font-size: 11px; }
}
@media (max-height: 560px) {
  button { padding: 8px 6px; min-height: 58px; }
  .icon  { width: 22px; height: 22px; }
}
</style>
</head>
<body>

<header>
  <div class="hrow">
    <h1>MacBook Controls</h1>
    <div class="hlinks">
      <a class="hlink" id="adv-toggle" href="#">Advanced</a>
      <a class="hlink" href="/change-password">Password</a>
      <a class="hlink" href="/logout">Lock</a>
    </div>
  </div>
  <div class="vol-row">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" style="flex-shrink:0"><path d="M3 9v6h4l5 5V4L7 9H3z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/></svg>
    <div class="vol-track"><div id="vol-fill"></div></div>
    <span id="vol-pct">—</span>
  </div>
</header>

<div class="card c-display">
  <div class="card-label">Display</div>
  <div class="row row-2">
    <button data-a="brightness_down"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3.5"/><path d="M12 3.5V5M12 19v1.5M5.22 5.22l1.06 1.06M17.72 17.72l1.06 1.06M3.5 12H5M19 12h1.5M5.22 18.78l1.06-1.06M17.72 6.28l1.06-1.06"/></svg><span class="sub">F1 · Dim</span></button>
    <button data-a="brightness_up">  <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="5"/><path d="M12 2V4M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg><span class="sub">F2 · Bright</span></button>
  </div>
</div>

<div class="card c-adv adv-hidden" id="adv-card">
  <div class="card-label">System</div>
  <div class="row row-2">
    <button data-a="mission_control"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="9" height="7" rx="1.5"/><rect x="13" y="3" width="9" height="7" rx="1.5"/><rect x="2" y="14" width="9" height="7" rx="1.5"/><rect x="13" y="14" width="9" height="7" rx="1.5"/></svg><span class="sub">F3 · Mission Control</span></button>
    <button data-a="launchpad"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="6" cy="6" r="2.5"/><circle cx="12" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="12" cy="12" r="2.5"/><circle cx="18" cy="12" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="12" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/></svg><span class="sub">F4 · Launchpad</span></button>
  </div>
  <div class="row row-2">
    <button data-a="kbd_bright_down"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="14" width="20" height="7" rx="2"/><path d="M6 14V9M10 14V7M14 14V7M18 14V9"/><path d="M7 4h2M15 4h2M11 3v2"/></svg><span class="sub">F5 · Kbd Dim</span></button>
    <button data-a="kbd_bright_up"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="14" width="20" height="7" rx="2"/><path d="M6 14V9M10 14V7M14 14V7M18 14V9"/><path d="M7 4h2M15 4h2M11 2v3"/></svg><span class="sub">F6 · Kbd Bright</span></button>
  </div>
</div>

<div class="card c-media">
  <div class="card-label">Media</div>
  <div class="row row-3">
    <button data-a="prev_track"><svg class="icon" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="5" width="2.5" height="14" rx="1.25"/><path d="M19.5 5L9.5 12l10 7V5z"/></svg><span class="sub">F7</span></button>
    <button data-a="play_pause" class="play"><svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M5 4.5L13.5 12 5 19.5V4.5z"/><rect x="15.5" y="4.5" width="2.5" height="15" rx="1.25"/><rect x="19.5" y="4.5" width="2.5" height="15" rx="1.25"/></svg><span class="sub">F8 · Play / Pause</span></button>
    <button data-a="next_track"><svg class="icon" viewBox="0 0 24 24" fill="currentColor"><rect x="17.5" y="5" width="2.5" height="14" rx="1.25"/><path d="M4.5 5l10 7-10 7V5z"/></svg><span class="sub">F9</span></button>
  </div>
</div>

<div class="card c-vol">
  <div class="card-label">Volume</div>
  <div class="row row-3">
    <button data-a="mute">      <svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3z"/><path d="M17 9l6 6M23 9l-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/></svg><span class="sub">F10 · Mute</span></button>
    <button data-a="volume_down"><svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3z"/><path d="M15.5 8.5a5 5 0 0 1 0 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/></svg><span class="sub">F11 · Down</span></button>
    <button data-a="volume_up">  <svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/></svg><span class="sub">F12 · Up</span></button>
  </div>
</div>

<footer>
  <span class="bm-label">Add to Home Screen — tap &amp; hold to copy:</span>
  <a class="bm-link" href="__SERVER_URL__">__SERVER_URL__</a>
  <span class="bm-label" style="margin-top:2px">or via IP: <a class="bm-link" style="font-size:11px;opacity:.7" href="__SERVER_IP__">__SERVER_IP__</a></span>
</footer>

<script>
const fill = document.getElementById('vol-fill');
const pct  = document.getElementById('vol-pct');
async function syncStatus() {
  try {
    const r = await fetch('/status');
    if (!r.ok) return;
    const d = await r.json();
    if (d.volume >= 0) { fill.style.width = d.volume + '%'; pct.textContent = d.volume + '%'; }
    fill.classList.toggle('muted', d.muted);
  } catch (_) {}
}
async function tap(action) {
  try {
    await fetch('/action', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }) });
    if (['mute','volume_up','volume_down'].includes(action)) setTimeout(syncStatus, 250);
  } catch (_) {}
}
document.querySelectorAll('button[data-a]').forEach(btn => {
  const a = btn.dataset.a;
  function down(e) { e.preventDefault(); btn.classList.add('tap'); tap(a); }
  function up()    { setTimeout(() => btn.classList.remove('tap'), 130); }
  btn.addEventListener('touchstart',  down, { passive: false });
  btn.addEventListener('touchend',    up);
  btn.addEventListener('touchcancel', up);
  btn.addEventListener('mousedown',   down);
  btn.addEventListener('mouseup',     up);
});
// Advanced mode toggle
const advCard   = document.getElementById('adv-card');
const advToggle = document.getElementById('adv-toggle');
let advOn = localStorage.getItem('mkc_adv') === '1';
function applyAdv() {
  advCard.classList.toggle('adv-hidden', !advOn);
  advToggle.style.opacity = advOn ? '1' : '0.55';
}
applyAdv();
advToggle.addEventListener('click', e => {
  e.preventDefault(); advOn = !advOn;
  localStorage.setItem('mkc_adv', advOn ? '1' : '0');
  applyAdv();
});
syncStatus();
setInterval(syncStatus, 4000);
</script>
</body>
</html>
"""

# ── HTTP handler ───────────────────────────────────────────────────────────────

_ERRORS_SETUP = {
    "mismatch": '<span class="error">Passwords don\'t match</span>',
    "short":    '<span class="error">Password must be at least 4 characters</span>',
    "empty":    '<span class="error">Password cannot be empty</span>',
}
_ERRORS_LOGIN = {
    "wrong":    '<span class="error">Wrong password — try again</span>',
}
_ERRORS_PW = {
    "wrong":    '<span class="error">Current password is incorrect</span>',
    "mismatch": '<span class="error">New passwords don\'t match</span>',
    "empty":    '<span class="error">New password cannot be empty</span>',
    "short":    '<span class="error">Password must be at least 4 characters</span>',
    "saved":    '<span class="success">Password updated ✓</span>',
}

class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Threaded server — each connection gets its own thread."""
    daemon_threads = True

class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # keep-alive: reuse TCP connection across redirect

    def log_message(self, *_):
        pass

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, code: int = 200):
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, cookie: str = None):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        query  = parse_qs(parsed.query)
        err    = query.get("error", [""])[0]
        ok     = "success" in query

        # ── Favicon + touch icon (public, no auth) ───────────────────────────────
        if path in ("/favicon.ico", "/favicon.png"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_FAVICON_PNG)))
            self.end_headers()
            self.wfile.write(_FAVICON_PNG)
            return
        if path == "/apple-touch-icon.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(_TOUCH_ICON_PNG)))
            self.end_headers()
            self.wfile.write(_TOUCH_ICON_PNG)
            return

        # ── Web app manifest (public) ─────────────────────────────────────────
        if path == "/manifest.json":
            manifest = json.dumps({
                "name": "MacBook Controls",
                "short_name": "MediaKeys",
                "start_url": f"{_BM_URL}/",
                "display": "standalone",
                "background_color": "#000000",
                "theme_color": "#000000",
                "icons": [{"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"}],
            })
            body = manifest.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # ── First-run setup (no password yet) ─────────────────────────────────
        if not _password:
            if path != "/setup":
                self._redirect("/setup")
            else:
                html = (_SETUP_HTML
                        .replace("__ERROR__", _ERRORS_SETUP.get(err, ""))
                        .replace("__BOOKMARK_URL__", _BM_URL))
                self._send_html(html)
            return

        # ── Login page ────────────────────────────────────────────────────────
        if path == "/login":
            html = (_LOGIN_HTML
                    .replace("__ERROR__", _ERRORS_LOGIN.get(err, ""))
                    .replace("__BOOKMARK_URL__", _BM_URL))
            self._send_html(html)
            return

        # ── Logout ────────────────────────────────────────────────────────────
        if path == "/logout":
            token = _get_cookie(self, COOKIE_NAME)
            _sessions.pop(token, None)
            _save_sessions_to_disk()
            self._redirect("/login", cookie=_cookie_set("", max_age=0))
            return

        # ── Auth gate ─────────────────────────────────────────────────────────
        if not _is_authed(self):
            self._redirect("/login")
            return

        # ── Authenticated routes ──────────────────────────────────────────────
        if path in ("/", "/index.html"):
            html = (_MAIN_HTML
                    .replace("__SERVER_URL__", _BM_URL)
                    .replace("__SERVER_IP__", _IP_URL))
            self._send_html(html)

        elif path == "/change-password":
            msg = _ERRORS_PW.get("saved" if ok else err, "")
            self._send_html(_CHANGE_PW_HTML.replace("__MSG__", msg))

        elif path == "/status":
            try:    self._send_json(200, _get_status())
            except Exception as e: self._send_json(500, {"error": str(e)})

        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        try:
            self._do_post()
        except Exception:
            import traceback
            traceback.print_exc()
            try:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except Exception:
                pass

    def _do_post(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        n      = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(n)
        params = parse_qs(body.decode())

        def p(key): return params.get(key, [""])[0]

        # ── First-run: set password ───────────────────────────────────────────
        if path == "/setup":
            if _password:
                self._redirect("/")
                return
            pw, pw2 = p("pw"), p("pw2")
            if not pw:          self._redirect("/setup?error=empty")
            elif pw != pw2:     self._redirect("/setup?error=mismatch")
            elif len(pw) < 4:   self._redirect("/setup?error=short")
            else:
                _save_password(pw)
                self._redirect("/", cookie=_cookie_set(_new_session()))
            return

        # ── Login ─────────────────────────────────────────────────────────────
        if path == "/login":
            if _password and _sec.compare_digest(p("pw"), _password):
                self._redirect("/", cookie=_cookie_set(_new_session()))
            else:
                self._redirect("/login?error=wrong")
            return

        # ── Auth gate ─────────────────────────────────────────────────────────
        if not _is_authed(self):
            self._send_json(401, {"error": "unauthorized"})
            return

        # ── Change password ───────────────────────────────────────────────────
        if path == "/change-password":
            cur, pw, pw2 = p("cur"), p("pw"), p("pw2")
            if not _sec.compare_digest(cur, _password):
                self._redirect("/change-password?error=wrong")
            elif not pw:            self._redirect("/change-password?error=empty")
            elif len(pw) < 4:       self._redirect("/change-password?error=short")
            elif pw != pw2:         self._redirect("/change-password?error=mismatch")
            else:
                # Invalidate all other sessions, keep current
                tok     = _get_cookie(self, COOKIE_NAME)
                cur_exp = _sessions.get(tok)
                _sessions.clear()
                if cur_exp: _sessions[tok] = cur_exp
                _save_password(pw)
                _save_sessions_to_disk()
                self._redirect("/change-password?success=1")
            return

        # ── Media action ──────────────────────────────────────────────────────
        if path == "/action":
            try:
                data = json.loads(body)
                name = data.get("action", "")
                fn   = _ACTIONS.get(name)
                if fn:
                    threading.Thread(target=fn, daemon=True).start()
                    self._send_json(200, {"ok": True})
                else:
                    self._send_json(400, {"error": f"unknown action: {name!r}"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self.send_response(404); self.end_headers()

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Change password from CLI
    if "--set-password" in sys.argv:
        idx = sys.argv.index("--set-password")
        if idx + 1 >= len(sys.argv):
            print("Usage: python3 server.py --set-password <newpassword>")
            sys.exit(1)
        _save_password(sys.argv[idx + 1])
        print(f"  ✓  Password saved to {SETTINGS_FILE}")
        sys.exit(0)

    print()
    _setup_swift()
    _setup_auth()

    _SERVER_HOST = _bonjour_host()
    _SERVER_IP   = _local_ip()
    _BM_URL      = f"http://{_SERVER_HOST}:{PORT}"
    _IP_URL      = f"http://{_SERVER_IP}:{PORT}"

    ax_ok = _check_accessibility()
    host  = _SERVER_HOST
    ip    = _SERVER_IP
    print()
    print("  ┌─────────────────────────────────────┐")
    print("  │       Apple MediaKey Control        │")
    print("  │                                     │")
    print(f"  │   iOS bookmark:                     │")
    print(f"  │   http://{host:<28s}│")
    print(f"  │                                     │")
    print(f"  │   Direct IP (fallback):             │")
    print(f"  │   http://{ip:<28s}│")
    print("  │                                     │")
    if ax_ok:
        print("  │   ✓  Accessibility: granted         │")
    else:
        print("  │   ✗  Accessibility: NOT granted     │")
        print("  │      Volume works. For media/       │")
        print("  │      brightness: System Settings    │")
        print("  │      → Privacy → Accessibility     │")
        print("  │      → add Terminal, then restart  │")
    print("  └─────────────────────────────────────┘")
    print()
    print("  Ctrl+C to stop\n")

    try:
        server = _Server(("0.0.0.0", PORT), _Handler)
    except OSError as e:
        if e.errno == 48:  # Address already in use
            print(f"\n  ⚠  Port {PORT} is already in use.")
            print("     MediaKeyControl.app may already be running.")
            print("     Quit the app first, then retry.\n")
        else:
            print(f"\n  ⚠  Could not start server: {e}\n")
        sys.exit(1)

    # ── Watchdog: exit when parent process (MediaKeyControl.app) dies ─────────
    # When the app is force-killed or crashes, this process gets reparented to
    # launchd (PID 1). Detect that and exit cleanly.
    _ppid = os.getppid()
    if _ppid > 1:   # started by the app, not a standalone shell session
        def _watch_parent():
            while True:
                time.sleep(3)
                if os.getppid() != _ppid:
                    os._exit(0)
        threading.Thread(target=_watch_parent, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
