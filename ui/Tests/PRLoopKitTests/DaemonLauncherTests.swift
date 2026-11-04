import Foundation
import PRLoopKit
import Testing

@Suite struct DaemonLauncherTests {
    private actor Recorder: DaemonLauncher {
        private(set) var runs: [[String]] = []

        func run(_ executable: String, _ arguments: [String]) {
            runs.append([executable] + arguments)
        }
    }

    private let file = URL.temporaryDirectory.appending(path: "launchd-label-\(UUID().uuidString)")

    @Test("kickstarts the label the daemon left behind")
    func label() async throws {
        try "local.review-queue\n".write(to: file, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: file) }
        let launcher = Recorder()
        try await launcher.start(labelFile: file, uid: 501)
        #expect(await launcher.runs == [["/bin/launchctl", "kickstart", "gui/501/local.review-queue"]])
    }

    @Test("falls back to local.pr-loop with no label file")
    func defaultLabel() async throws {
        let launcher = Recorder()
        try await launcher.start(labelFile: file, uid: 501)
        #expect(await launcher.runs == [["/bin/launchctl", "kickstart", "gui/501/local.pr-loop"]])
    }

    @Test("the socket lives in the state directory")
    func socket() {
        #expect(DaemonLocation.socket.path().hasSuffix("/.local/state/pr-loop/api.sock"))
    }
}
