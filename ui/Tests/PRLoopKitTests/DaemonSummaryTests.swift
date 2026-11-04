import Foundation
import PRLoopKit
import Testing

@Suite struct DaemonSummaryTests {
    @Test(
        "version, uptime and active repos read as one line",
        arguments: [(3540, "59 min"), (14340, "3 h"), (172805, "2 d")] as [(TimeInterval, String)])
    func line(uptime: TimeInterval, reads: String) throws {
        let info = try Snapshots.info()
        let summary = DaemonSummary(info, try Snapshots.queue(), now: info.startedAt.addingTimeInterval(uptime))
        #expect(summary.line == "1.0.0 (3dc9b3f) · up \(reads) · 3 active repos of 4")
    }
}
