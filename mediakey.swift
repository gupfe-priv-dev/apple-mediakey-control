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
