// Bot Monitoring Room menu-bar app for macOS 13+. No dependencies; build with ./build-app.sh.
//
// It keeps the local Bot Monitoring Room server running (an installed `bot-monitor` command, or the
// checkout the app was built from), shows how many bots are busy right in the menu bar,
// lists live relays and the latest alert, and can start itself at login.

import Cocoa
import ServiceManagement

private let zh = Locale.preferredLanguages.first?.hasPrefix("zh") ?? false
private func L(_ en: String, _ cn: String) -> String { zh ? cn : en }

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let port = Int(ProcessInfo.processInfo.environment["BOT_OFFICE_PORT"] ?? "") ?? 10000
    private var base: String { "http://127.0.0.1:\(port)" }
    private var statusItem: NSStatusItem!
    private var server: Process?
    private var timer: Timer?

    private var reachable = false
    private var starting = false
    private var busy = 0
    private var attention = 0
    private var liveFlows: [(id: String, text: String)] = []
    private var latestAlert: (title: String, flow: String?)?

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = Self.botIcon()
        statusItem.button?.imagePosition = .imageLeading
        let menu = NSMenu()
        menu.delegate = self
        statusItem.menu = menu
        poll(startIfDown: true)
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.poll(startIfDown: false) }
    }

    func applicationWillTerminate(_ notification: Notification) {
        server?.terminate()
    }

    // MARK: server

    private func startServer() {
        guard server == nil, !starting else { return }
        starting = true
        let repo = Bundle.main.object(forInfoDictionaryKey: "BotMonitorRepo") as? String ?? ""
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        // A login shell finds pipx/uv/Homebrew installs; arguments are passed, never spliced in.
        process.arguments = ["-lc", """
            if command -v bot-monitor >/dev/null 2>&1; then exec bot-monitor --port "$2"; fi
            if [ -f "$1/backend/server.py" ]; then exec python3 "$1/backend/server.py" --port "$2"; fi
            echo "Bot Monitoring Room not found: install it with pipx or rebuild this app from a checkout" >&2; exit 1
            """, "bot-monitor", repo, String(port)]
        let log = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Bot Monitoring Room.log")
        FileManager.default.createFile(atPath: log.path, contents: nil)
        if let handle = try? FileHandle(forWritingTo: log) {
            handle.seekToEndOfFile()
            process.standardOutput = handle
            process.standardError = handle
        }
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.server = nil }
        }
        do {
            try process.run()
            server = process
        } catch {
            NSLog("Bot Monitoring Room: could not start the server: \(error)")
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self] in self?.starting = false }
    }

    // MARK: polling

    private func fetch(_ path: String, _ done: @escaping (Any?) -> Void) {
        guard let url = URL(string: base + path) else { return done(nil) }
        var request = URLRequest(url: url, timeoutInterval: 3)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200
            let json = ok ? data.flatMap { try? JSONSerialization.jsonObject(with: $0) } : nil
            DispatchQueue.main.async { done(json) }
        }.resume()
    }

    private func poll(startIfDown: Bool) {
        let lang = zh ? "zh" : "en"
        fetch("/api/office?lang=\(lang)") { [weak self] json in
            guard let self else { return }
            guard let office = json as? [String: Any], let agents = office["agents"] as? [[String: Any]] else {
                self.reachable = false
                if startIfDown || self.server == nil { self.startServer() }
                self.refreshButton()
                return
            }
            self.reachable = true
            self.busy = agents.filter { ($0["state"] as? String) != "idle" }.count
            self.attention = agents.filter { ($0["detail"] as? String) == "awaiting" || ($0["state"] as? String) == "error" }.count
            self.refreshButton()
        }
        fetch("/api/flows?hours=24&lang=\(lang)") { [weak self] json in
            guard let self, let data = json as? [String: Any], let flows = data["flows"] as? [[String: Any]] else { return }
            self.liveFlows = flows.filter { ($0["active"] as? Bool) == true }.prefix(3).compactMap { flow in
                guard let id = flow["id"] as? String else { return nil }
                let trigger = flow["trigger"] as? [String: Any]
                let text = (trigger?["text"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? L("Scheduled relay", "定时任务")
                return (id, String(text.prefix(48)))
            }
        }
        fetch("/api/alerts") { [weak self] json in
            guard let self, let data = json as? [String: Any], let alerts = data["alerts"] as? [[String: Any]], let first = alerts.first,
                  let title = first["title"] as? String else { return }
            self.latestAlert = (title, first["flowId"] as? String)
        }
    }

    private func refreshButton() {
        guard let button = statusItem.button else { return }
        var title = busy > 0 ? " \(busy)" : ""
        if attention > 0 { title += " !" }
        button.title = reachable ? title : " …"
        button.toolTip = reachable ? L("Bot Monitoring Room", "Bot监控室") : L("Bot Monitoring Room is starting…", "Bot监控室正在启动…")
    }

    // MARK: menu

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        if reachable {
            var parts = [L("\(busy) busy", "\(busy) 位在忙")]
            if !liveFlows.isEmpty { parts.append(L("\(liveFlows.count) live", "\(liveFlows.count) 场进行中")) }
            if attention > 0 { parts.append(L("\(attention) need you", "\(attention) 件等你处理")) }
            menu.addItem(disabled(parts.joined(separator: " · ")))
            for flow in liveFlows {
                menu.addItem(item("▶︎ " + flow.text, #selector(openFlow(_:)), represented: flow.id))
            }
            if let alert = latestAlert {
                menu.addItem(item("🔔 " + String(alert.title.prefix(52)), #selector(openFlow(_:)), represented: alert.flow ?? ""))
            }
        } else {
            menu.addItem(disabled(L("Starting Bot Monitoring Room…", "正在启动Bot监控室…")))
        }
        menu.addItem(.separator())
        menu.addItem(item(L("Open Bot Monitoring Room", "打开Bot监控室"), #selector(openHome), key: "o"))
        menu.addItem(item(L("Big-screen mode", "大屏模式"), #selector(openTV)))
        menu.addItem(item(L("Settings…", "设置…"), #selector(openSettings), key: ","))
        menu.addItem(.separator())
        let login = item(L("Start at login", "登录时启动"), #selector(toggleLogin))
        login.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(login)
        menu.addItem(item(L("Quit Bot Monitoring Room", "退出Bot监控室"), #selector(quit), key: "q"))
    }

    private func disabled(_ title: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }

    private func item(_ title: String, _ action: Selector, key: String = "", represented: String? = nil) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        item.representedObject = represented
        return item
    }

    private func open(_ path: String) {
        if let url = URL(string: base + path) { NSWorkspace.shared.open(url) }
    }

    @objc private func openHome() { open("/") }
    @objc private func openTV() { open("/?tv=1") }
    @objc private func openSettings() { open("/settings") }
    @objc private func openFlow(_ sender: NSMenuItem) {
        let id = sender.representedObject as? String ?? ""
        open(id.isEmpty ? "/" : "/#flow=\(id)")
    }

    @objc private func toggleLogin() {
        do {
            if SMAppService.mainApp.status == .enabled {
                try SMAppService.mainApp.unregister()
            } else {
                try SMAppService.mainApp.register()
            }
        } catch {
            let alert = NSAlert()
            alert.messageText = L("Couldn't change the login item", "没能修改登录项")
            alert.informativeText = L("Move Bot Monitoring Room.app to the Applications folder and try again.\n\n\(error.localizedDescription)",
                                      "请把 Bot Monitoring Room.app 放进“应用程序”文件夹后再试。\n\n\(error.localizedDescription)")
            alert.runModal()
        }
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    // MARK: icon

    /// The Bot Monitoring Room mark as a menu-bar template image: a bot head with an antenna.
    private static func botIcon() -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: true) { _ in
            NSColor.black.setStroke()
            NSColor.black.setFill()
            let head = NSBezierPath(roundedRect: NSRect(x: 2.5, y: 6, width: 13, height: 10), xRadius: 4, yRadius: 4)
            head.lineWidth = 1.6
            head.stroke()
            NSBezierPath(roundedRect: NSRect(x: 6, y: 9, width: 1.8, height: 4), xRadius: 0.9, yRadius: 0.9).fill()
            NSBezierPath(roundedRect: NSRect(x: 10.2, y: 9, width: 1.8, height: 4), xRadius: 0.9, yRadius: 0.9).fill()
            let antenna = NSBezierPath()
            antenna.move(to: NSPoint(x: 9, y: 6))
            antenna.line(to: NSPoint(x: 9, y: 3.2))
            antenna.lineWidth = 1.4
            antenna.stroke()
            NSBezierPath(ovalIn: NSRect(x: 7.6, y: 0.6, width: 2.8, height: 2.8)).fill()
            return true
        }
        image.isTemplate = true
        return image
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
// Quit cleanly (and stop the server we started) on `kill` or logout, not only from the menu.
signal(SIGTERM, SIG_IGN)
let terminateSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
terminateSource.setEventHandler { NSApp.terminate(nil) }
terminateSource.resume()
app.setActivationPolicy(.accessory)
app.run()
