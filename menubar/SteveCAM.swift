// SteveCAM menu-bar app (task MENUBAR): shows the connector's status from
// ~/.stevecam/status.json + connector.pid and can start / stop / restart it.
// SwiftUI MenuBarExtra, macOS 13+, compiled with:
//   swiftc -O -swift-version 5 -parse-as-library SteveCAM.swift -o SteveCAM
// Never shows or stores pairing codes or keys. The repo path comes from the
// Info.plist key SCRepo.

import AppKit
import Darwin
import Foundation
import SwiftUI

let agentLabel = "com.stevecam.connector"
let repoPath = (Bundle.main.infoDictionary?["SCRepo"] as? String) ?? ""

// ---------------------------------------------------------------- helpers --
func homeDir() -> String { NSHomeDirectory() }
func steveHome() -> String { homeDir() + "/.stevecam" }

@discardableResult
func runTool(_ launch: String, _ args: [String]) -> (Int32, String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: launch)
    p.arguments = args
    let out = Pipe()
    p.standardOutput = out
    p.standardError = Pipe()
    do { try p.run() } catch { return (-1, "") }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(data: data, encoding: .utf8) ?? "")
}

func pidAlive(_ pid: Int32) -> Bool {
    if pid <= 0 { return false }
    if kill(pid, 0) == 0 { return true }
    return errno == EPERM
}

/// The exact PID's command line must mention connector.py before we trust
/// the pidfile or send it any signal. Never kill by name.
func pidRunsConnector(_ pid: Int32) -> Bool {
    let (_rc, cmd) = runTool("/bin/ps", ["-o", "command=", "-p", String(pid)])
    return cmd.contains("connector.py")
}

func connectorPID() -> Int32? {
    guard let text = try? String(contentsOfFile: steveHome() + "/connector.pid",
                                 encoding: .utf8),
          let pid = Int32(text.trimmingCharacters(
            in: .whitespacesAndNewlines))
    else { return nil }
    return (pidAlive(pid) && pidRunsConnector(pid)) ? pid : nil
}

func readStatusJSON() -> [String: Any]? {
    guard let data = FileManager.default.contents(
            atPath: steveHome() + "/status.json"),
          let obj = try? JSONSerialization.jsonObject(with: data)
            as? [String: Any]
    else { return nil }
    return obj
}

// ------------------------------------------------------------ stop guard --
// MENUBAR2: what Stop / Restart should do while status.json "state" may
// mark a run as in progress. Pure decision, no UI, no process access.
// "busy" is the state connector.py writes during a run ("working" is the
// label the menu shows for it); force=1 on a stevecam:// URL overrides.
enum StopDecision {
    case proceed
    case confirm
    case refuse
}

func stopDecision(state: String?, force: Bool, fromURL: Bool)
    -> StopDecision {
    if force { return .proceed }            // stevecam://stop?force=1
    if state == "busy" || state == "working" {
        return fromURL ? .refuse : .confirm
    }
    return .proceed
}

func openSettingsWindow() {
    // macOS 13 fallback only: the showSettingsWindow:/showPreferencesWindow:
    // selectors no longer open a SwiftUI Settings scene on macOS 14+; the
    // menu uses SettingsLink there (see MenuContent).
    NSApplication.shared.activate(ignoringOtherApps: true)
    if !NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil,
                         from: nil) {
        _ = NSApp.sendAction(Selector(("showPreferencesWindow:")), to: nil,
                             from: nil)
    }
}

// ------------------------------------------------------------------ model --
final class AppModel: ObservableObject {
    @Published var statusLine = "Stopped"
    @Published var commit = ""
    @Published var name = ""
    @Published var fingerprint = ""
    @Published var lastRun = ""
    @Published var running = false
    @Published var busy = false
    @Published var turnOffAfter = 0        // minutes; 0 = Never (default)
    @Published var startAtLogin = false

    private var idleSince: Date?

    init() {
        loadSettings()
        startAtLogin = readRunAtLoad()
        refresh()
        Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) {
            [weak self] _ in self?.refresh()
        }
    }

    func refresh() {
        let pid = connectorPID()
        running = pid != nil
        let st = readStatusJSON()
        commit = st?["commit"] as? String ?? ""
        name = st?["connector_name"] as? String ?? ""
        fingerprint = st?["fingerprint"] as? String ?? ""
        if let lr = st?["last_run"] as? [String: Any] {
            lastRun = "Last run: \(lr["action"] as? String ?? "?") "
                + "\(lr["at"] as? String ?? "")"
        } else {
            lastRun = ""
        }
        let state = st?["state"] as? String ?? ""
        if let pid = pid {
            if (state == "busy" || state == "working"),
               let action = st?["action"] as? String {
                let pct = ((st?["progress"] as? Double) ?? 0) * 100
                statusLine = String(format: "Working: %@ %d%%", action,
                                    Int(pct.rounded()))
            } else {
                statusLine = "Running, pid \(pid)"
            }
        } else {
            statusLine = "Stopped"
        }
        // "Turn off after": stop once status.json has said idle that long.
        if running && state == "idle" && turnOffAfter > 0 {
            if let since = idleSince {
                if Date().timeIntervalSince(since)
                    >= Double(turnOffAfter) * 60 {
                    idleSince = nil
                    stop()
                }
            } else {
                idleSince = Date()
            }
        } else {
            idleSince = nil
        }
    }

    func start() {
        guard !running, !busy else { return }
        busy = true
        DispatchQueue.global(qos: .userInitiated).async {
            _ = runTool("/bin/launchctl",
                        ["kickstart", "gui/\(getuid())/\(agentLabel)"])
            let deadline = Date().addingTimeInterval(15)
            while connectorPID() == nil && Date() < deadline {
                usleep(500_000)
            }
            DispatchQueue.main.async {
                self.busy = false
                self.refresh()
            }
        }
    }

    /// status.json "state" as of now ("" when the file is missing).
    func currentStatusState() -> String {
        (readStatusJSON()?["state"] as? String) ?? ""
    }

    /// One timestamped line in ~/.stevecam/menubar.log when a URL action is
    /// refused because a run is in progress.
    func logRefusal(_ action: String) {
        let ts = ISO8601DateFormatter().string(from: Date())
        let line = "\(ts) refused \(action): run in progress\n"
        let path = steveHome() + "/menubar.log"
        if let fh = FileHandle(forWritingAtPath: path) {
            fh.seekToEndOfFile()
            if let data = line.data(using: .utf8) { fh.write(data) }
            try? fh.close()
        } else {
            try? FileManager.default.createDirectory(
                atPath: steveHome(), withIntermediateDirectories: true)
            try? line.data(using: .utf8)?
                .write(to: URL(fileURLWithPath: path))
        }
    }

    /// The menu's question while a run is in progress; true only when the
    /// user clicks Stop (Cancel does nothing).
    private func confirmStop() -> Bool {
        let alert = NSAlert()
        alert.messageText = "A run is in progress. Stop anyway?"
        alert.addButton(withTitle: "Stop")
        alert.addButton(withTitle: "Cancel")
        return alert.runModal() == .alertFirstButtonReturn
    }

    func stop(fromURL: Bool = false, force: Bool = false) {
        guard !busy else { return }
        guard let pid = connectorPID() else { refresh(); return }
        switch stopDecision(state: currentStatusState(), force: force,
                            fromURL: fromURL) {
        case .refuse:
            logRefusal("stop")
            return
        case .confirm:
            guard confirmStop() else { return }
        case .proceed:
            break
        }
        performStop(pid, restartAfter: false, confirmed: true)
    }

    /// The ONLY SIGTERM call site (the probe in pidAlive sends no signal).
    /// Reached only after the stopDecision above: `confirmed` is true only
    /// when the decision was .proceed or the user approved the alert, and
    /// this returns unless it is true.
    private func performStop(_ pid: Int32, restartAfter: Bool,
                             confirmed: Bool) {
        guard confirmed else { return }
        guard !busy else { return }
        busy = true
        DispatchQueue.global(qos: .userInitiated).async {
            if pidRunsConnector(pid) { kill(pid, SIGTERM) }
            let stopDeadline = Date().addingTimeInterval(45)
            while pidAlive(pid) && Date() < stopDeadline { usleep(500_000) }
            if restartAfter {
                _ = runTool("/bin/launchctl",
                            ["kickstart", "gui/\(getuid())/\(agentLabel)"])
                let startDeadline = Date().addingTimeInterval(15)
                while connectorPID() == nil && Date() < startDeadline {
                    usleep(500_000)
                }
            }
            DispatchQueue.main.async {
                self.busy = false
                self.refresh()
            }
        }
    }

    func restart(fromURL: Bool = false, force: Bool = false) {
        guard !busy else { return }
        guard let pid = connectorPID() else { start(); return }
        switch stopDecision(state: currentStatusState(), force: force,
                            fromURL: fromURL) {
        case .refuse:
            logRefusal("restart")
            return
        case .confirm:
            guard confirmStop() else { return }
        case .proceed:
            break
        }
        performStop(pid, restartAfter: true, confirmed: true)
    }

    func openLog() {
        NSWorkspace.shared.open(URL(fileURLWithPath: steveHome()
                                    + "/connector.log"))
    }

    func handle(_ url: URL) {
        // MENUBAR2: force=1 is only ever read from the URL
        // (stevecam://stop?force=1 / stevecam://restart?force=1); the menu
        // path always runs the decision (alert while busy). start is
        // unchanged.
        let force = url.query.map {
            $0.components(separatedBy: "&").contains("force=1")
        } ?? false
        switch url.host {
        case "start": start()
        case "stop": stop(fromURL: true, force: force)
        case "restart": restart(fromURL: true, force: force)
        default: break
        }
    }

    // ------------------------------------------------------------ settings --
    private func settingsPath() -> String { steveHome() + "/menubar.json" }

    func loadSettings() {
        guard let data = FileManager.default.contents(atPath: settingsPath()),
              let obj = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any],
              let mins = obj["turn_off_after_minutes"] as? Int else { return }
        turnOffAfter = mins
    }

    func saveSettings() {
        try? FileManager.default.createDirectory(atPath: steveHome(),
                                                 withIntermediateDirectories:
                                                    true)
        let obj: [String: Any] = ["turn_off_after_minutes": turnOffAfter]
        if let data = try? JSONSerialization.data(withJSONObject: obj) {
            try? data.write(to: URL(fileURLWithPath: settingsPath()))
        }
    }

    private func agentPlistPath() -> String {
        homeDir() + "/Library/LaunchAgents/\(agentLabel).plist"
    }

    func readRunAtLoad() -> Bool {
        guard let d = NSMutableDictionary(contentsOfFile: agentPlistPath()),
              let v = d["RunAtLoad"] as? Bool else { return false }
        return v
    }

    /// Rewrites RunAtLoad in ~/Library/LaunchAgents/com.stevecam.connector
    /// .plist; takes effect at next login. No-op if the plist is not there.
    func setRunAtLoad(_ on: Bool) {
        guard let d = NSMutableDictionary(contentsOfFile: agentPlistPath())
        else {
            startAtLogin = false
            return
        }
        d["RunAtLoad"] = on
        if let data = try? PropertyListSerialization.data(
            fromPropertyList: d, format: .xml, options: 0) {
            try? data.write(to: URL(fileURLWithPath: agentPlistPath()),
                            options: .atomic)
            startAtLogin = on
        } else {
            startAtLogin = readRunAtLoad()
        }
    }
}

// ---------------------------------------------------------------- delegate --
final class AppDelegate: NSObject, NSApplicationDelegate {
    func application(_ application: NSApplication, open urls: [URL]) {
        urls.forEach { AppState.shared.model.handle($0) }
    }
}

// Global so the delegate can reach the model (URL scheme stevecam://...).
final class AppState {
    static let shared = AppState()
    let model = AppModel()
}

// ------------------------------------------------------------------- views --
struct MenuContent: View {
    @ObservedObject var model: AppModel

    var body: some View {
        Text(model.statusLine)
        if !model.commit.isEmpty { Text("main \(model.commit)") }
        if !model.name.isEmpty {
            Text("\(model.name) · \(String(model.fingerprint.prefix(8)))")
        }
        if !model.lastRun.isEmpty { Text(model.lastRun) }
        Divider()
        Button("Start") { model.start() }
            .disabled(model.running || model.busy)
        Button("Stop") { model.stop() }
            .disabled(!model.running || model.busy)
        Button("Restart") { model.restart() }.disabled(model.busy)
        Button("Open log") { model.openLog() }
        // The legacy selectors in openSettingsWindow() are broken on this
        // macOS; use SwiftUI's SettingsLink (macOS 14+) and keep the
        // selector path only as the macOS 13 fallback. Activation is done
        // via .simultaneousGesture so the Settings window comes to front.
        if #available(macOS 14, *) {
            SettingsLink {
                Text("Settings...")
            }
            .simultaneousGesture(
                TapGesture().onEnded {
                    NSApplication.shared.activate(ignoringOtherApps: true)
                })
        } else {
            Button("Settings...") { openSettingsWindow() }
        }
        Divider()
        Button("Quit SteveCAM") { NSApplication.shared.terminate(nil) }
            .keyboardShortcut("q")
    }
}

struct SettingsView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        Form {
            Toggle("Start at login", isOn: Binding(
                get: { model.startAtLogin },
                set: { model.setRunAtLoad($0) }))
            Picker("Turn off after", selection: $model.turnOffAfter) {
                Text("Never").tag(0)
                Text("30 min").tag(30)
                Text("2 h").tag(120)
                Text("8 h").tag(480)
            }
            .onChange(of: model.turnOffAfter) { _ in model.saveSettings() }
            if !repoPath.isEmpty { Text("repo: \(repoPath)") }
        }
        .padding(12)
        .frame(width: 340)
    }
}

// --------------------------------------------------------------------- app --
@main
struct SteveCAMApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        MenuBarExtra("SteveCAM", systemImage: "c.circle") {
            MenuContent(model: AppState.shared.model)
        }
        Settings {
            SettingsView(model: AppState.shared.model)
        }
    }
}
