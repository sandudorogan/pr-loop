import PRLoopKit
import Testing

@Suite struct ScopeTests {
    @Test("a running pass keeps the older verdict and says it is updating")
    func running() throws {
        let scope = try #require(try Snapshots.item(0).scope)
        #expect(scope.status == .running)
        #expect(!scope.isCurrent)
        #expect(scope.style?.label == "Some creep")
        #expect(scope.note == "Updating for the new head…")
        #expect(scope.outOfScope.map(\.what) == ["The date filter defaults to the last 12 months"])
        #expect(scope.changes.map(\.mark) == ["~", "~"])
    }

    @Test("a fresh verdict needs no note, and a PR without a pass has no scope")
    func ready() throws {
        let scope = try #require(try Snapshots.item(2).scope)
        #expect(scope.style?.label == "Focused")
        #expect(scope.note == nil)
        #expect(scope.help == "Every change serves the filter chips.")
        #expect(try Snapshots.item(1).scope == nil)
    }

    @Test("a failed first pass has no verdict, and its error is in the tooltip")
    func failed() throws {
        let scope = try #require(try Snapshots.item(3).scope)
        #expect(scope.verdict == nil)
        #expect(scope.note == "Summary failed")
        #expect(scope.help == "Summary failed\ncodex summarize exited 1: stream error")
    }

    @Test(
        "words every verdict",
        arguments: [("focused", "Focused"), ("some-creep", "Some creep"), ("sprawling", "Sprawling"), ("odd", "odd")])
    func verdict(raw: String, label: String) {
        #expect(ScopeStyle(ScopeVerdict(rawValue: raw)).label == label)
    }
}
