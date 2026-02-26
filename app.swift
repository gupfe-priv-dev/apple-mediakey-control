import AppKit
import Foundation

let PORT = 8765
let SOCK_PATH = "/tmp/mediakeycontrol.sock"
let LOG_PATH: String = {
    let lib = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
    let dir = lib.appendingPathComponent("Logs")
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    return dir.appendingPathComponent("MediaKeyControl.log").path
}()

// NX key constants (IOKit/hidsystem/ev_keymap.h)
let NX_BRIGHT_UP:   Int = 2
let NX_BRIGHT_DOWN: Int = 3
let NX_MUTE:        Int = 7
let NX_PLAY:        Int = 16
let NX_NEXT:        Int = 17
let NX_PREV:        Int = 18

func mklog(_ msg: String) {
    let line = "[\(Date())] [MKC-App] \(msg)\n"
    NSLog("[MKC] %@", msg)
    if let data = line.data(using: .utf8) {
        if !FileManager.default.fileExists(atPath: LOG_PATH) {
            FileManager.default.createFile(atPath: LOG_PATH, contents: nil)
        }
        if let fh = FileHandle(forWritingAtPath: LOG_PATH) {
            fh.seekToEndOfFile(); fh.write(data); fh.closeFile()
        }
    }
}

// Must be called on main thread — NSEvent.otherEvent is AppKit (not thread-safe)
func sendNXKey(_ keyType: Int) {
    let t = ProcessInfo.processInfo.systemUptime
    let dn = NSEvent.otherEvent(
        with: .systemDefined, location: NSPoint(x: 0, y: 0),
        modifierFlags: NSEvent.ModifierFlags(rawValue: 0xa00),
        timestamp: t, windowNumber: 0, context: nil,
        subtype: 8, data1: (keyType << 16) | (0xa << 8), data2: -1)
    let up = NSEvent.otherEvent(
        with: .systemDefined, location: NSPoint(x: 0, y: 0),
        modifierFlags: NSEvent.ModifierFlags(rawValue: 0xb00),
        timestamp: t, windowNumber: 0, context: nil,
        subtype: 8, data1: (keyType << 16) | (0xb << 8), data2: -1)
    dn?.cgEvent?.post(tap: .cgSessionEventTap)
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.02) {
        up?.cgEvent?.post(tap: .cgSessionEventTap)
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var serverProcess: Process?
    var urlMenuItem: NSMenuItem!
    var bonjourURL: String = "http://localhost:\(PORT)"

    func applicationDidFinishLaunching(_ note: Notification) {
        NSApp.setActivationPolicy(.accessory)
        buildMenu()        // icon appears immediately — nothing blocking beyond this point
        startKeyServer()   // background thread, non-blocking

        // All blocking work on background thread; startServer called on main after
        DispatchQueue.global().async {
            self.freePort()
            DispatchQueue.main.async { self.startServer() }
        }

        // Accessibility check after UI is fully rendered (never blocks main thread)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            self.refreshAccessibility(force: false)
        }

        mklog("startup — Accessibility: \(AXIsProcessTrusted() ? "GRANTED ✓" : "NOT GRANTED ✗")")
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { self.openInBrowser() }
    }

    // ── Accessibility: reset stale TCC entries, then re-request both entries ──
    // Resets com.gunnar.mediakeycontrol, which covers both
    // "MediaKeyControl" (executable) and "MediaKeyControl.app" (bundle) entries.
    // Always runs on background thread; the prompt call is dispatched to main.
    func refreshAccessibility(force: Bool) {
        guard force || !AXIsProcessTrusted() else { return }
        DispatchQueue.global().async {
            // Remove stale entries so fresh ones can be toggled on
            let reset = Process()
            reset.executableURL = URL(fileURLWithPath: "/usr/bin/tccutil")
            reset.arguments = ["reset", "Accessibility", "com.gunnar.mediakeycontrol"]
            reset.standardOutput = Pipe(); reset.standardError = Pipe()
            try? reset.run(); reset.waitUntilExit()

            // Prompt — opens System Settings → Accessibility, registers this process.
            // Both the executable and bundle entries will appear ready to toggle on.
            DispatchQueue.main.async {
                let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
                AXIsProcessTrustedWithOptions([key: true] as CFDictionary)
            }
        }
    }

    @objc func grantAccessibility() {
        refreshAccessibility(force: true)
    }

    // ── Unix socket listener ──────────────────────────────────────────────────
    func startKeyServer() {
        try? FileManager.default.removeItem(atPath: SOCK_PATH)
        DispatchQueue.global(qos: .userInteractive).async {
            var addr = sockaddr_un()
            addr.sun_family = sa_family_t(AF_UNIX)
            let sunPathLen = MemoryLayout.size(ofValue: addr.sun_path) - 1
            withUnsafeMutablePointer(to: &addr.sun_path.0) { ptr in
                SOCK_PATH.withCString { _ = strncpy(ptr, $0, sunPathLen) }
            }
            let fd = socket(AF_UNIX, SOCK_STREAM, 0)
            guard fd >= 0 else { mklog("socket() failed errno=\(errno)"); return }
            let bindOK = withUnsafePointer(to: &addr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
                }
            } == 0
            guard bindOK else { mklog("bind() failed errno=\(errno)"); close(fd); return }
            guard listen(fd, 8) == 0 else { mklog("listen() failed"); close(fd); return }
            mklog("socket ready at \(SOCK_PATH)")
            while true {
                let client = accept(fd, nil, nil)
                guard client >= 0 else { continue }
                var buf = [UInt8](repeating: 0, count: 16)
                let n = read(client, &buf, buf.count)
                close(client)
                guard n > 0 else { continue }
                let msg = String(bytes: buf[0..<n], encoding: .utf8)?
                    .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                if let keyType = Int(msg) {
                    DispatchQueue.main.async { sendNXKey(keyType) }
                }
            }
        }
    }

    func buildMenu() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let btn = statusItem.button {
            if let img = NSImage(systemSymbolName: "keyboard", accessibilityDescription: "MediaKeyControl") {
                btn.image = img
            } else {
                btn.title = "⌨"
            }
        }
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Open Controls…", action: #selector(openInBrowser), keyEquivalent: "o"))
        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "Grant Accessibility…", action: #selector(grantAccessibility), keyEquivalent: ""))
        menu.addItem(.separator())
        urlMenuItem = NSMenuItem(title: "Starting…", action: nil, keyEquivalent: "")
        urlMenuItem.isEnabled = false
        menu.addItem(urlMenuItem)
        menu.addItem(.separator())
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        let verItem = NSMenuItem(title: "v\(version)", action: nil, keyEquivalent: "")
        verItem.isEnabled = false
        menu.addItem(verItem)
        menu.addItem(NSMenuItem(title: "Quit MediaKeyControl",
                                action: #selector(NSApplication.terminate(_:)),
                                keyEquivalent: "q"))
        statusItem.menu = menu
    }

    // Kill any process already listening on PORT (runs on background thread only)
    func freePort() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        p.arguments = ["-ti", ":\(PORT)"]
        let pipe = Pipe()
        p.standardOutput = pipe; p.standardError = Pipe()
        try? p.run(); p.waitUntilExit()
        let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        for pidStr in out.components(separatedBy: .newlines) {
            let s = pidStr.trimmingCharacters(in: .whitespacesAndNewlines)
            if let pid = Int32(s) {
                mklog("freePort: killing PID \(pid) on port \(PORT)")
                kill(pid, SIGTERM)
            }
        }
        if !out.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            Thread.sleep(forTimeInterval: 0.4)
        }
    }

    func startServer() {
        // freePort() already called on background thread before this — do NOT call again here
        guard let resources = Bundle.main.resourcePath else { return }
        let script = resources + "/server.py"
        let candidates = ["/usr/bin/python3", "/usr/local/bin/python3", "/opt/homebrew/bin/python3"]
        guard let python = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            urlMenuItem.title = "⚠ python3 not found"; return
        }
        serverProcess = Process()
        serverProcess!.executableURL = URL(fileURLWithPath: python)
        serverProcess!.arguments = [script]
        if !FileManager.default.fileExists(atPath: LOG_PATH) {
            FileManager.default.createFile(atPath: LOG_PATH, contents: nil)
        }
        if let fh = FileHandle(forWritingAtPath: LOG_PATH) {
            fh.seekToEndOfFile()
            serverProcess!.standardOutput = fh
            serverProcess!.standardError  = fh
        }
        try? serverProcess!.run()
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.8) {
            let host = self.bonjourHostname()
            let url  = "http://\(host):\(PORT)"
            DispatchQueue.main.async {
                self.bonjourURL = url
                self.urlMenuItem.title = url
            }
        }
    }

    @objc func openInBrowser() {
        guard let url = URL(string: bonjourURL) else { return }
        NSWorkspace.shared.open(url)
    }

    func bonjourHostname() -> String {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/sbin/scutil")
        p.arguments = ["--get", "LocalHostName"]
        let pipe = Pipe()
        p.standardOutput = pipe
        try? p.run(); p.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let name = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return name.isEmpty ? "localhost" : "\(name).local"
    }

    func applicationWillTerminate(_ note: Notification) {
        serverProcess?.terminate()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
