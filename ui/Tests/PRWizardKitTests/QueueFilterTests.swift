import PRWizardKit
import Testing

@Suite struct QueueFilterTests {
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

    @Test("sections follow the groups and hide when empty")
    func sections() throws {
        let items = try Snapshots.queue().items
        let all = QueueFilter().sections(items)
        #expect(all.map(\.title) == ["In Work", "Up Next", "Ready", "Waiting"])
        #expect(all.map(\.items.count) == [1, 1, 1, 1])
        #expect(QueueFilter(repo: "iprally/gitops").sections(items).map(\.kind) == [.waiting])
    }

    @Test("a paused PR goes to the last section")
    func paused() throws {
        let items = try Snapshots.queue().items + [Snapshots.item(1, ["group": "paused", "paused": true])]
        #expect(QueueFilter().sections(items).map(\.title) == ["In Work", "Up Next", "Ready", "Waiting", "Paused"])
    }

    @Test("the selection resumes only when every PR is paused")
    func resumes() throws {
        let paused = try Snapshots.item(1, ["paused": true])
        #expect([paused].resumes)
        #expect(try ![paused, Snapshots.item(0)].resumes)
        #expect(![QueueItem]().resumes)
    }

    @Test("an unknown group waits")
    func unknownGroup() throws {
        let item = try Snapshots.item(0, ["group": .string("parked")])
        #expect(QueueFilter().sections([item]).map(\.kind) == [.waiting])
    }
}
