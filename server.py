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
BASE = Path(__file__).parent

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

_ACTIONS = {
    # AppleScript — no Accessibility needed
    "volume_up":       _vol_up,
    "volume_down":     _vol_down,
    "mute":            _mute_toggle,
    # NX key events — need Accessibility permission
    "brightness_down": lambda: _nx(_NX_BRIGHT_DOWN),
    "brightness_up":   lambda: _nx(_NX_BRIGHT_UP),
    "prev_track":      lambda: _nx(_NX_PREV),
    "play_pause":      lambda: _nx(_NX_PLAY),
    "next_track":      lambda: _nx(_NX_NEXT),
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

_META = """<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<link rel="icon" type="image/png" href="data:image/png;base64,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">"""

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
.icon { font-size: 30px; line-height: 1; pointer-events: none; }
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
  .icon  { font-size: 26px; }
  .sub   { font-size: 10px; }
  footer { padding: 4px 4px 2px; }
  .bm-label { display: none; }
  .bm-link  { font-size: 11px; }
}
@media (max-height: 560px) {
  button { padding: 8px 6px; min-height: 58px; }
  .icon  { font-size: 22px; }
}
</style>
</head>
<body>

<header>
  <div class="hrow">
    <h1>MacBook Controls</h1>
    <div class="hlinks">
      <a class="hlink" href="/change-password">Password</a>
      <a class="hlink" href="/logout">Lock</a>
    </div>
  </div>
  <div class="vol-row">
    <span>🔊</span>
    <div class="vol-track"><div id="vol-fill"></div></div>
    <span id="vol-pct">—</span>
  </div>
</header>

<div class="card c-display">
  <div class="card-label">Display</div>
  <div class="row row-2">
    <button data-a="brightness_down"><span class="icon">🔅</span><span class="sub">F1 · Dim</span></button>
    <button data-a="brightness_up">  <span class="icon">🔆</span><span class="sub">F2 · Bright</span></button>
  </div>
</div>

<div class="card c-media">
  <div class="card-label">Media</div>
  <div class="row row-3">
    <button data-a="prev_track"><span class="icon">⏮</span><span class="sub">F7</span></button>
    <button data-a="play_pause" class="play"><span class="icon">⏯</span><span class="sub">F8 · Play / Pause</span></button>
    <button data-a="next_track"><span class="icon">⏭</span><span class="sub">F9</span></button>
  </div>
</div>

<div class="card c-vol">
  <div class="card-label">Volume</div>
  <div class="row row-3">
    <button data-a="mute">      <span class="icon">🔇</span><span class="sub">F10 · Mute</span></button>
    <button data-a="volume_down"><span class="icon">🔉</span><span class="sub">F11 · Down</span></button>
    <button data-a="volume_up">  <span class="icon">🔊</span><span class="sub">F12 · Up</span></button>
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

        # ── Web app manifest (public) ─────────────────────────────────────────
        if path == "/manifest.json":
            manifest = json.dumps({
                "name": "MacBook Controls",
                "short_name": "MediaKeys",
                "start_url": f"{_BM_URL}/",
                "display": "standalone",
                "background_color": "#000000",
                "theme_color": "#000000",
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
