import PRLoopKit
import Testing

@Suite struct QueueFilterTests {
    private func toApprove(_ items: [QueueItem]) -> [String]? {
        QueueFilter().sections(items).first?.rows.map(\.id)
    }

    private func keys(_ filter: QueueFilter) throws -> [String] {
        filter.items(try Snapshots.queue().items).map(\.key)
    }

    @Test("all repos keeps the daemon's order")
    func all() throws {
        #expect(
            try keys(QueueFilter())
                == ["iprally/iprally#17190", "iprally/iprally#17201", "iprally/iprally#17166", "iprally/gitops#412"])
    }

    @Test("a project keeps only its PRs")
    func project() throws {
        #expect(try keys(QueueFilter(repo: "iprally/gitops")) == ["iprally/gitops#412"])
    }

    @Test(
        "text matches the number, the project or the title",
        arguments: [
            ("17201", ["iprally/iprally#17201"]),
            (" #412 ", ["iprally/gitops#412"]),
            ("GITOPS", ["iprally/gitops#412"]),
            ("filters", ["iprally/iprally#17190", "iprally/iprally#17166"]),
            ("nothing like it", []),
        ])
    func text(text: String, expected: [String]) throws {
        #expect(try keys(QueueFilter(text: text)) == expected)
    }

    @Test("colleagues' PRs, then mine, each split into stages with the ready one first, then Done")
    func sections() throws {
        let all = QueueFilter().sections(try Snapshots.queue().items, done: [try Snapshots.historyEntry()])
        #expect(all.map(\.title) == ["To Approve", "My PRs", "Done"])
        #expect(
            all.map { $0.stages.map(\.id) } == [
                ["toApprove.ready", "toApprove.queued"], ["mine.active", "mine.parked"], [],
            ])
        #expect(
            all.map { $0.rows.map(\.id) } == [
                ["iprally/iprally#17166", "iprally/iprally#17201"],
                ["iprally/iprally#17190", "iprally/gitops#412"],
                ["iprally/iprally#17120"],
            ])
        #expect(QueueFilter(repo: "iprally/gitops").sections(try Snapshots.queue().items).map(\.kind) == [.mine])
    }

    @Test("an idle PR the fix lane still owes a pass is fix queued, any other idle PR is parked")
    func idle() throws {
        let owed = try Snapshots.item(3, ["fix_queued": true])
        let parked = try Snapshots.item(3, ["number": 413, "key": "iprally/gitops#413"])
        let stages = QueueFilter().sections([parked, owed]).flatMap(\.stages)
        #expect(stages.map(\.id) == ["mine.fixQueued", "mine.parked"])
    }

    @Test("a paused PR goes last in its section")
    func paused() throws {
        let items = try [Snapshots.item(1, ["group": "paused", "paused": true]), Snapshots.item(2)]
        #expect(toApprove(items) == ["iprally/iprally#17166", "iprally/iprally#17201"])
    }

    @Test("Done shows only done entries, and a done item leaves the to-do list")
    func done() throws {
        let open = try Snapshots.historyEntry(["done": false, "state": "settled"])
        let finishing = try Snapshots.item(2, ["done": true, "group": "active"])
        #expect(QueueFilter().sections([finishing], done: [open]).isEmpty)
    }

    @Test("the project and the text filter Done too")
    func doneFilter() throws {
        let entry = try Snapshots.historyEntry()
        #expect(QueueFilter(text: "sticky").sections([], done: [entry]).map(\.kind) == [.done])
        #expect(QueueFilter(repo: "iprally/gitops").sections([], done: [entry]).isEmpty)
    }

    @Test("the selection resumes only when every PR is paused")
    func resumes() throws {
        let paused = try Snapshots.item(1, ["paused": true])
        #expect([paused].resumes)
        #expect(try ![paused, Snapshots.item(0)].resumes)
        #expect(![QueueItem]().resumes)
    }

    @Test("an unknown group waits behind the ready ones")
    func unknownGroup() throws {
        let items = try [Snapshots.item(1, ["group": .string("parked")]), Snapshots.item(2)]
        #expect(toApprove(items) == ["iprally/iprally#17166", "iprally/iprally#17201"])
    }
}
