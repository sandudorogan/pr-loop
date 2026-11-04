import PRLoopKit
import Testing

@Suite struct PRMarkersTests {
    private func markers(_ patch: JSONValue = [:]) throws -> PRMarkers {
        PRMarkers(repo: "iprally/iprally", config: try PRConfigs.config(merging: patch))
    }

    @Test(
        "each path reads its level from layers",
        arguments: [
            ("review.reviewers", PRMarkers.Source.pr),
            ("fix.gates", .project("iprally/iprally")),
            ("fix.model", .default),
            ("review.enabled", .default),
        ])
    func level(path: String, source: PRMarkers.Source) throws {
        #expect(try markers().source(of: path) == source)
    }

    @Test("a section takes its strongest path, and a parent path covers the leaves under it")
    func section() throws {
        let markers = try markers()
        #expect(markers.source(of: ["fix.model", "fix.gates"]) == .project("iprally/iprally"))
        #expect(markers.source(of: ["fix.gates", "review.reviewers"]) == .pr)
        #expect(markers.source(of: "review") == .pr)
        #expect(markers.overridden(within: ["review.enabled", "review"]) == ["review.reviewers"])
    }

    @Test(
        "a lane label locks the lane over every layer",
        arguments: [("no-auto-review", "review.enabled"), ("no-auto-fix", "fix.enabled")])
    func labelLock(label: String, path: String) throws {
        let markers = try markers(["labels": [.string(label)], "layers": ["pr": [.string(path)]]])
        #expect(markers.source(of: path) == .label(label))
        #expect(markers.source(of: path == "fix.enabled" ? "review.enabled" : "fix.enabled") == .default)
    }

    @Test("the row cue names every overridden path")
    func rowCue() throws {
        let items = try Snapshots.queue().items
        let overridden = try #require(items.first { $0.number == 17201 })
        #expect(overridden.overrideHelp == "Overridden for this PR: review.reviewers")
        #expect(items.first { $0.number == 17190 }?.overrideHelp == nil)
    }
}
