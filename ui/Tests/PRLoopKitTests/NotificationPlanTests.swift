import Foundation
import PRLoopKit
import Testing

@Suite struct NotificationPlanTests {
    private func keys(_ ops: [NotificationOp]) -> [String] {
        ops.map { op in
            switch op {
            case .post(let notification): "post \(notification.key)"
            case .remove(let key): "remove \(key)"
            }
        }
    }

    @Test("the events fixture posts the ready PR and removes the withdrawn one, live and in a catch-up")
    func fixture() throws {
        let page = try Fixture.decode(EventPage.self, from: "events.json")
        let expected = ["post iprally/iprally#17166", "remove iprally/iprally#17120"]
        #expect(keys(LivePlan.plan(page)) == expected)
        #expect(keys(CatchUp.plan(page, in: try Snapshots.queue())) == expected)
    }

    @Test("the same head made ready twice posts once")
    func sameHead() throws {
        let page = try Events.page("e.3", [Events.ready(1), Events.ready(3)])
        #expect(keys(LivePlan.plan(page)) == ["post iprally/iprally#17166"])
    }

    @Test("per key the highest seq wins: a withdrawal at a new head removes by key and cancels the post")
    func latestWins() throws {
        let page = try Events.page("e.3", [Events.withdrawn(3), Events.ready(1)])
        #expect(keys(LivePlan.plan(page)) == ["remove iprally/iprally#17166"])
    }

    @Test("a later ready reposts after a withdrawal")
    func readyAgain() throws {
        let page = try Events.page("e.3", [Events.withdrawn(1), Events.ready(2)])
        #expect(keys(LivePlan.plan(page)) == ["post iprally/iprally#17166"])
    }

    @Test("unknown types are ignored and cancel nothing")
    func unknownTypes() throws {
        let page = try Events.page("e.3", [Events.ready(1), Events.event("pr_merged", 2)])
        #expect(keys(LivePlan.plan(page)) == ["post iprally/iprally#17166"])
    }

    @Test("the same number in two repos stays two notifications, in seq order")
    func twoRepos() throws {
        let page = try Events.page(
            "e.3", [Events.ready(2, number: 412, repo: "iprally/gitops"), Events.ready(1, number: 412)])
        #expect(keys(LivePlan.plan(page)) == ["post iprally/iprally#412", "post iprally/gitops#412"])
    }

    @Test(
        "a catch-up drops a post when the PR left the queue, is not ready, or has a new head",
        arguments: [
            (17166, Events.ready17166, true), (9999, Events.ready17166, false),
            (17201, "c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f6", false), (17166, "0123456789ab", false),
        ])
    func catchUpFilter(number: Int, head: String, posts: Bool) throws {
        let page = try Events.page(
            "e.3", [Events.ready(1, number: number, head: head), Events.withdrawn(2, number: 17120)])
        let expected = (posts ? ["post iprally/iprally#\(number)"] : []) + ["remove iprally/iprally#17120"]
        #expect(keys(CatchUp.plan(page, in: try Snapshots.queue())) == expected)
        #expect(LivePlan.plan(page).count == 2)
    }

    @Test(
        "the subtitle names the project, number, author and verdict",
        arguments: [
            ("clean", "iprally #17166 · colleague · clean"),
            ("quality-only", "iprally #17166 · colleague · notes only"),
        ])
    func subtitle(verdict: String, subtitle: String) throws {
        let page = try Events.page("e.1", [Events.event("ready_for_approval", 1, verdict: verdict)])
        guard case .post(let notification) = try #require(LivePlan.plan(page).first) else {
            Issue.record("expected a post")
            return
        }
        #expect(notification.subtitle == subtitle)
    }

    @Test("content: event id as identifier, key as thread, title, body and url")
    func content() throws {
        let event = try #require(try Fixture.decode(EventPage.self, from: "events.json").events.first)
        let notification = ReadyNotification(event)
        #expect(notification.id == "ready_for_approval:iprally/iprally#17166@9f8e7d6c5b4a")
        #expect(notification.key == "iprally/iprally#17166")
        #expect(notification.title == "Ready for your approval")
        #expect(notification.body == "refactor(ui): one sub per hop in the filters")
        #expect(notification.url == URL(string: "https://github.com/iprally/iprally/pull/17166"))
    }
}
