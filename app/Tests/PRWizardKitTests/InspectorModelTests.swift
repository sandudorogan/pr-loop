import Foundation
import PRWizardKit
import Testing

@Suite struct InspectorModelTests {
    private let live = 0
    private let queued = 1
    private let ready = 2
    private let gitops = 3

    private func model(_ index: Int, _ patch: [String: JSONValue] = [:]) throws -> InspectorModel {
        InspectorModel(try Snapshots.item(index, patch))
    }

    @Test("formats the pull request lines")
    func pullRequest() throws {
        let model = try model(live)
        #expect(model.title == "iprally #17190")
        #expect(model.head == "5e0c2d9a41b7")
        #expect(model.lines == "+212 −40")
        #expect(model.labels == "None")
        let labeled = try self.model(gitops, ["labels": .array([.string("no-auto-review"), .string("infra")])])
        #expect(labeled.labels == "no-auto-review, infra")
    }

    @Test("says whether the review and the fix ran at this head")
    func heads() throws {
        #expect(try model(live).reviewedHead == "Older head 0aa1c3e9b2d4")
        #expect(try model(live).fixedHead == "Older head 0aa1c3e9b2d4")
        #expect(try model(ready).reviewedHead == "This head")
        #expect(try model(gitops).fixedHead == "This head")
    }

    @Test("reads the verdict in the status words")
    func verdict() throws {
        #expect(try model(live).verdict == "Findings posted")
        #expect(try model(ready).verdict == "Notes only")
        #expect(try model(queued).verdict == nil)
    }

    @Test("counts failed fix passes", arguments: [(0, "None"), (1, "1 failed pass"), (3, "3 failed passes in a row")])
    func fixErrors(errors: Int, text: String) throws {
        let fix: JSONValue = .object([
            "sha": .string("77aa0c1e2f3d4b5a69788796a5b4c3d2e1f00f1e"), "current": .bool(true),
            "status": .string("tests-red"), "note": .string("Karma red"), "errors": .number(Double(errors)),
            "parked": .bool(errors >= 3), "at": .string("2026-10-25T10:31:12+03:00"),
        ])
        #expect(try model(gitops, ["fix": fix]).fixErrors == text)
    }

    @Test("names the live lane and each reviewer's state")
    func liveRun() throws {
        let model = try model(live)
        let reviewers = try #require(model.item.active?.reviewers)
        #expect(model.lane == "Review")
        #expect(reviewers.map(InspectorModel.state) == ["Running", "Waiting · attempt 2", "Clean"])
        #expect(model.reviewerLabel("opus") == "Claude Opus 5.5")
        #expect(model.reviewerLabel("sonnet") == "sonnet")
    }

    @Test("summarises a digest from an older head")
    func staleFindings() throws {
        let findings = try #require(try Snapshots.item(live).findings)
        #expect(!findings.isCurrent)
        #expect(findings.header == "Round 1 · head 0aa1c3e9b2d4 · 4 at or above the fix floor")
        #expect(findings.staleNote == "Not reviewed at this head")
        #expect(findings.reviewedAt == findings.reviewers.last?.at)
        #expect(findings.reviewers.map(\.result.label) == ["Findings", "Findings", "Clean"])
        #expect(findings.top.first?.location == "ui/src/cljs/iprally_ui/search/events.cljs:57")
        #expect(
            findings.conventionsLine
                == "Followed AGENTS.md · CLAUDE.md · ui/AGENTS.md · ui/CLAUDE.md · .clj-kondo/config.edn")
    }

    @Test("has no stale note at the current head")
    func currentFindings() throws {
        let findings = try #require(try Snapshots.item(ready).findings)
        #expect(findings.staleNote == nil)
        #expect(findings.reviewers.map(\.result.label) == ["Clean", "Clean", "Findings"])
    }

    @Test("leaves findings and review empty before the first review")
    func noFindings() throws {
        let model = try model(queued)
        #expect(model.item.findings == nil)
        #expect(model.reviewedHead == nil)
        #expect(model.fixedHead == nil)
        #expect(model.fixErrors == nil)
        #expect(model.lane == nil)
    }

    @Test("marks a reviewer skipped for lack of conventions")
    func skipped() throws {
        let digest = """
            {"head": "9f8e7d6c5b4a39281706f5e4d3c2b1a098f7e6d5", "current": true, "round": 1, "at_floor": 0,
             "conventions": [], "top": [],
             "reviewers": [{"id": "quality", "label": "Quality", "result": "skipped", "engine": "claude",
                            "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "at_floor": 0,
                            "top": [], "url": null, "at": "2026-10-24T17:40:02+03:00"}]}
            """
        let patch = try JSONDecoder().decode(JSONValue.self, from: Data(digest.utf8))
        let findings = try #require(try model(ready, ["findings": patch]).item.findings)
        let reviewer = try #require(findings.reviewers.first)
        #expect(reviewer.result == .skipped)
        #expect(reviewer.result.label == "Skipped: no conventions")
        #expect(reviewer.counts.nonZero.isEmpty)
        #expect(findings.conventionsLine == "No project conventions")
    }

    @Test(
        "words every reviewer result",
        arguments: [
            ("posted", "Findings"), ("notes-only", "Notes only"), ("clean", "Clean"),
            ("skipped", "Skipped: no conventions"), ("failed", "Failed"), ("limited", "Usage limit"),
            ("timeout", "timeout"),
        ])
    func resultLabel(raw: String, label: String) {
        #expect(ReviewerResult(rawValue: raw).label == label)
    }
}
