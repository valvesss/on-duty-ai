// on-duty notifier app (~/Applications/on-duty.app). Notifications sent from it carry the app's icon and name instead of
// "Script Editor"; opening it by hand shows the dashboard. It runs as an accessory AppKit app (no Dock icon) because macOS only
// shows the notification permission prompt to a real GUI process.
//
//   notify --title T [--subtitle S] [--body B] [--sound] [--url U] [--thread ID]
//   notify --status      print the notification authorization state
//   notify --delivered   list what's in Notification Center
//
// Exit codes: 0 delivered, 2 notifications not allowed, 3 error.
import AppKit
import UserNotifications

let args = Array(CommandLine.arguments.dropFirst())
func arg(_ key: String) -> String? {
    guard let i = args.firstIndex(of: key), i + 1 < args.count else { return nil }
    return args[i + 1]
}

final class App: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let center = UNUserNotificationCenter.current()
    let url = arg("--url") ?? ""

    func applicationDidFinishLaunching(_ n: Notification) {
        center.delegate = self
        if args.isEmpty {  // opened from Spotlight/Finder (or by a click on an old notification): show the dashboard
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {  // give a notification click time to arrive first
                var port = 4269
                let cfg = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".on-duty/config.json")
                if let d = try? Data(contentsOf: cfg), let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any], let p = j["port"] as? Int { port = p }
                let p = Process()
                p.executableURL = URL(fileURLWithPath: "/usr/bin/open")
                p.arguments = ["http://localhost:\(port)/"]
                try? p.run()
                exit(0)
            }
            return
        }
        if args.contains("--status") {
            center.getNotificationSettings { s in
                print("authorization=\(s.authorizationStatus.rawValue) alert=\(s.alertSetting.rawValue) sound=\(s.soundSetting.rawValue)")
                exit(0)
            }
            return
        }
        if args.contains("--delivered") {  // what's currently sitting in Notification Center (used by tests)
            center.getDeliveredNotifications { list in
                for n in list { print("\(n.request.content.title) | \(n.request.content.subtitle) | \(n.request.content.body)") }
                exit(0)
            }
            return
        }
        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            guard granted else {
                FileHandle.standardError.write(Data("notifications not allowed: \(String(describing: error))\n".utf8))
                exit(2)
            }
            let c = UNMutableNotificationContent()
            c.title = arg("--title") ?? "on-duty"
            if let s = arg("--subtitle") { c.subtitle = s }
            if let b = arg("--body") { c.body = b }
            if args.contains("--sound") { c.sound = .default }
            if let t = arg("--thread") { c.threadIdentifier = t }
            c.userInfo = ["url": self.url]
            self.center.add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil)) { err in
                if err != nil { exit(3) }
                // Stay alive a while only when there's something to open on click.
                if self.url.isEmpty { exit(0) }
                DispatchQueue.main.asyncAfter(deadline: .now() + 25) { exit(0) }
            }
        }
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, willPresent n: UNNotification,
                                withCompletionHandler h: @escaping (UNNotificationPresentationOptions) -> Void) {
        h([.banner, .list, .sound])
    }

    func userNotificationCenter(_ c: UNUserNotificationCenter, didReceive r: UNNotificationResponse,
                                withCompletionHandler h: @escaping () -> Void) {
        if let u = r.notification.request.content.userInfo["url"] as? String, !u.isEmpty {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/open")
            p.arguments = [u]
            try? p.run()
        }
        h()
        exit(0)
    }
}

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
