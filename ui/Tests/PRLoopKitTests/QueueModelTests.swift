import Foundation
import PRLoopKit
import Testing

@Suite struct QueueModelTests {
    @Test("queue.json decodes every item, project and pool")
    func queueDecodes() throws {
        let snapshot = try Fixture.decode(QueueSnapshot.self, from: "queue.json")
        #expect(snapshot.rev == "b71e09c4d2a35f18")
        #expect(snapshot.items.map(\.group) == [.active, .queued, .ready, .idle, .active])
        #expect(snapshot.projects.map(\.status) == [.active, .active, .active, .noCheckout])
        #expect(snapshot.lanes.pools.map(\.lane) == [.review, .fix])
        let counts: [Int] = [
            snapshot.counts.active, snapshot.counts.queued, snapshot.counts.ready, snapshot.counts.idle,
        ]
        #expect(counts == [2, 1, 1, 1])
    }

    @Test("an active fix says what it works on")
    func activeFix() throws {
        let item = try #require(Fixture.decode(QueueSnapshot.self, from: "queue.json").items.last)
        let fix = try #require(item.active?.fix)
        #expect(item.active?.lane == .fix)
        #expect(fix.step == .testing)
        #expect(fix.items.map(\.kind) == [.thread, .comment, .ci])
        #expect(
            fix.help == """
                Running the gates · 3 items
                • [high] The tree drops keys whose value is nil (opus, tree.cljs:42)
                • Could the nodes start collapsed? (aino)
                • CI job test (ubuntu-latest) failed
                """)
    }

    @Test("a merge-only pass names the conflict, a fresh one only its step")
    func fixHelpWithoutItems() throws {
        let progress = { (step: String, conflict: Bool) in
            try JSONDecoder.daemon.decode(
                FixProgress.self,
                from: Data(
                    #"{"step": "\#(step)", "since": "2026-10-25T12:02:58+03:00", "conflict": \#(conflict), "items": []}"#
                        .utf8))
        }
        #expect(try progress("merging", true).help == "Merging the base · 1 item\n• Merge conflict with the base")
        #expect(try progress("collecting", false).help == "Reading the feedback")
    }

    @Test("an active review carries each reviewer's progress")
    func activeRun() throws {
        let item = try #require(Fixture.decode(QueueSnapshot.self, from: "queue.json").items.first)
        let active = try #require(item.active)
        #expect(active.lane == .review)
        #expect(active.reviewers?.map(\.state) == [.running, .waiting, .clean])
        #expect(item.review?.verdict == .posted)
        #expect(item.fix?.isParked == false)
        #expect(item.findings?.isCurrent == false)
    }

    @Test("the findings digest keeps counts, floor and top findings")
    func findingsDigest() throws {
        let items = try Fixture.decode(QueueSnapshot.self, from: "queue.json").items
        let findings = try #require(items[2].findings)
        let quality = try #require(findings.reviewers.last)
        #expect(findings.atFloor == 2)
        #expect(quality.result == .posted)
        let counts: [Int] = [quality.counts.critical, quality.counts.high, quality.counts.medium, quality.counts.low]
        #expect(counts == [0, 0, 2, 1])
        #expect(quality.top.allSatisfy { $0.reviewer == nil })
        #expect(findings.top.map(\.severity) == [.medium, .medium, .low])
        #expect(findings.top.first?.reviewer == "quality")
    }

    @Test("a project without a checkout has no conventions")
    func projectWithoutCheckout() throws {
        let project = try #require(Fixture.decode(QueueSnapshot.self, from: "queue.json").projects.last)
        #expect(project.isAvailable == false)
        #expect(project.checkout == nil)
        #expect(project.conventions == nil)
    }

    @Test("an item's ref is its wire key")
    func refMatchesKey() throws {
        let items = try Fixture.decode(QueueSnapshot.self, from: "queue.json").items
        #expect(items.allSatisfy { $0.ref.id == $0.key })
        #expect(items.last?.ref == PRRef(repo: "sandudorogan/dataspex", number: 57))
    }

    @Test("times keep their offset")
    func timesWithOffset() throws {
        let snapshot = try Fixture.decode(QueueSnapshot.self, from: "queue.json")
        #expect(snapshot.generatedAt == Date(timeIntervalSince1970: 1_792_918_990))
    }

    @Test("info.json decodes identity, refresh, config and paths")
    func infoDecodes() throws {
        let info = try Fixture.decode(DaemonInfo.self, from: "info.json")
        #expect(info.api == 1)
        #expect(info.uptime == 10862)
        #expect(info.refresh.interval == 300)
        #expect(info.config.realPath.hasSuffix("chezmoi/.pr-loop/config.json"))
        #expect(info.paths.socket.hasSuffix("pr-loop/api.sock"))
        #expect(info.projects.count == 4)
    }

    @Test("unknown fields are ignored")
    func unknownFields() throws {
        let json = #"{"id": "review", "lane": "review", "repo": null, "workers": 3, "busy": 1, "pending": 0, "new": 1}"#
        let pool = try JSONDecoder.daemon.decode(Pool.self, from: Data(json.utf8))
        #expect(pool.workers == 3)
    }

    @Test(
        "open enums keep known and unknown values",
        arguments: [("no-checkout", ProjectStatus.noCheckout), ("paused", .unknown("paused"))])
    func openEnumValues(raw: String, status: ProjectStatus) throws {
        let json = Data(#""\#(raw)""#.utf8)
        #expect(try JSONDecoder.daemon.decode(ProjectStatus.self, from: json) == status)
        #expect(try JSONEncoder().encode(status) == json)
    }
}
