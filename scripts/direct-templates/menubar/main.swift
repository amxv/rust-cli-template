import AppKit
import Darwin
import Foundation
import ServiceManagement

private let product = "__APP_NAME__"
private let command = "__CLI__"
private let docsAddress = "__SITE__/docs/"
private let versionKey = "AppReleaseVersion"

private func cliURL() -> URL {
    Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent(command)
}

// open -n -g deliberately starts a fresh instance after a bundle replacement.
// A lock avoids duplicate menu icons while an earlier process exits.
private final class SingleInstanceLock {
    private let descriptor: Int32

    init?() {
        let file = Darwin.open("/tmp/__CLI__-menubar-\(getuid()).lock", O_CREAT | O_RDWR, 0o600)
        guard file >= 0 else { return nil }
        guard flock(file, LOCK_EX | LOCK_NB) == 0 else {
            Darwin.close(file)
            return nil
        }
        descriptor = file
    }

    deinit { Darwin.close(descriptor) }
}

private struct CommandResult {
    let code: Int32
    let output: String
}

private final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let menu = NSMenu()
    private var status: NSStatusItem!
    private var checkInProgress = false
    private var updating = false
    private var automaticUpdates = false
    private var relaunching = false
    // Capture the RUNNING version immediately: on-disk Info.plist may later change.
    private let launchVersion = Bundle.main.object(forInfoDictionaryKey: versionKey) as? String ?? "unknown"
    private var versionTimer: Timer?
    private lazy var automaticItem = makeItem("Automatic Updates (Daily)", #selector(toggleAutomaticUpdates), "arrow.clockwise")
    private lazy var loginItem = makeItem("Launch Menu Bar at Login", #selector(toggleLogin), "power")
    private lazy var checkItem = makeItem("Check for Updates…", #selector(checkUpdates), "arrow.down.circle")
    private lazy var versionItem: NSMenuItem = {
        let item = NSMenuItem(title: "\(product) v\(launchVersion)", action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        status = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        status.button?.title = "__MENU_LETTER__"
        status.button?.font = .systemFont(ofSize: 14, weight: .semibold)
        status.button?.toolTip = product
        menu.delegate = self
        menu.autoenablesItems = false
        menu.addItem(checkItem)
        menu.addItem(makeItem("Open Documentation", #selector(openDocumentation), "book"))
        menu.addItem(.separator())
        menu.addItem(automaticItem)
        menu.addItem(loginItem)
        menu.addItem(versionItem)
        menu.addItem(.separator())
        menu.addItem(makeItem("Quit Menu Bar", #selector(quit), "xmark.circle"))
        status.menu = menu
        refreshPreferences()
        versionTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            self?.relaunchIfUpdated()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        versionTimer?.invalidate()
    }

    func menuWillOpen(_ menu: NSMenu) {
        relaunchIfUpdated()
        refreshPreferences()
    }

    private func makeItem(_ title: String, _ selector: Selector, _ symbol: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        item.target = self
        item.image = NSImage(systemSymbolName: symbol, accessibilityDescription: title)
        item.image?.isTemplate = true
        return item
    }

    private func runCLI(_ arguments: [String], completion: @escaping (CommandResult) -> Void) {
        let executable = cliURL()
        DispatchQueue.global(qos: .utility).async {
            let process = Process()
            process.executableURL = executable
            process.arguments = arguments
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe
            do {
                try process.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                let result = CommandResult(code: process.terminationStatus, output: String(decoding: data, as: UTF8.self))
                DispatchQueue.main.async { completion(result) }
            } catch {
                DispatchQueue.main.async {
                    completion(CommandResult(code: 1, output: error.localizedDescription))
                }
            }
        }
    }

    private func alert(_ title: String, _ message: String) {
        let panel = NSAlert()
        panel.messageText = title
        panel.informativeText = message.trimmingCharacters(in: .whitespacesAndNewlines)
        panel.addButton(withTitle: "OK")
        NSApp.activate(ignoringOtherApps: true)
        panel.runModal()
    }

    private func refreshPreferences() {
        loginItem.state = SMAppService.mainApp.status == .enabled ? .on : .off
        runCLI(["auto-update", "status"]) { [weak self] result in
            guard let self else { return }
            if result.code == 0 {
                self.automaticUpdates = result.output.contains("on (every 24 hours)")
                self.automaticItem.state = self.automaticUpdates ? .on : .off
            }
        }
    }

    @objc private func toggleAutomaticUpdates() {
        let selected = automaticUpdates ? "off" : "on"
        automaticItem.isEnabled = false
        runCLI(["auto-update", selected]) { [weak self] result in
            guard let self else { return }
            self.automaticItem.isEnabled = true
            if result.code != 0 { self.alert("Couldn't change automatic updates", result.output) }
            self.refreshPreferences()
        }
    }

    @objc private func toggleLogin() {
        do {
            if SMAppService.mainApp.status == .enabled {
                try SMAppService.mainApp.unregister()
            } else {
                try SMAppService.mainApp.register()
            }
            refreshPreferences()
        } catch {
            alert("Couldn't change login startup", error.localizedDescription)
        }
    }

    @objc private func checkUpdates() {
        guard !checkInProgress && !updating else { return }
        checkInProgress = true
        checkItem.isEnabled = false
        runCLI(["upgrade", "--check"]) { [weak self] result in
            guard let self else { return }
            self.checkInProgress = false
            self.checkItem.isEnabled = true
            guard result.code == 0 else {
                self.alert("Couldn't check for updates", result.output)
                return
            }
            guard result.output.contains("Update available.") else {
                self.alert("Up to date", result.output)
                return
            }
            let prompt = NSAlert()
            prompt.messageText = "New \(product) version available"
            prompt.informativeText = result.output
            prompt.addButton(withTitle: "Upgrade")
            prompt.addButton(withTitle: "Later")
            NSApp.activate(ignoringOtherApps: true)
            if prompt.runModal() == .alertFirstButtonReturn {
                self.updating = true
                self.runCLI(["upgrade"]) { [weak self] updated in
                    guard let self else { return }
                    self.updating = false
                    if updated.code != 0 { self.alert("Upgrade failed", updated.output) }
                    else { self.relaunchIfUpdated() }
                }
            }
        }
    }

    @objc private func openDocumentation() {
        if let url = URL(string: docsAddress) { NSWorkspace.shared.open(url) }
    }

    @objc private func quit() { NSApp.terminate(nil) }

    private func relaunchIfUpdated() {
        guard !relaunching && !updating else { return }
        let infoURL = Bundle.main.bundleURL.appendingPathComponent("Contents/Info.plist")
        guard let contents = NSDictionary(contentsOf: infoURL),
              let installed = contents[versionKey] as? String,
              installed != launchVersion else { return }

        // A tiny independent helper waits for this process's lock to close.
        // LaunchServices can otherwise bring the old application to the front.
        let helper = Process()
        helper.executableURL = URL(fileURLWithPath: "/bin/sh")
        helper.arguments = [
            "-c",
            "for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do kill -0 \"$1\" 2>/dev/null || break; sleep 0.1; done; exec /usr/bin/open -n -g \"$2\" --args --after-upgrade",
            "__CLI__-relaunch", String(getpid()), Bundle.main.bundleURL.path
        ]
        helper.standardInput = FileHandle.nullDevice
        helper.standardOutput = FileHandle.nullDevice
        helper.standardError = FileHandle.nullDevice
        do {
            try helper.run()
            relaunching = true
            NSApp.terminate(nil)
        } catch {
            NSLog("Couldn't relaunch the updated menu bar app: %@", error.localizedDescription)
        }
    }
}

if CommandLine.arguments.contains("--version") {
    print("\(product) \(Bundle.main.object(forInfoDictionaryKey: versionKey) as? String ?? "unknown")")
    exit(0)
}
if CommandLine.arguments.contains("--check") {
    guard FileManager.default.isExecutableFile(atPath: cliURL().path) else {
        fputs("Companion CLI is missing next to the app\n", stderr)
        exit(1)
    }
    print("Swift menu bar bundle and companion CLI are ready")
    exit(0)
}

guard let singleton = SingleInstanceLock() else { exit(0) }
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
private let delegate = AppDelegate()
application.delegate = delegate
withExtendedLifetime(singleton) { application.run() }
