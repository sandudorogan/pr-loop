import PRWizardKit
import Testing

@Suite struct ReviewerSummaryTests {
    private let reviewers: [ReviewerConfig]

    init() throws {
        reviewers = try Settings.envelope().config.review.reviewers
    }

    private func project(_ conventions: JSONValue) throws -> Project {
        try Snapshots.project(0, ["conventions": conventions])
    }

    @Test("the defaults read engine · model · effort, then their traits")
    func defaults() {
        let summaries = reviewers.map { ReviewerSummary($0) }
        #expect(summaries.map(\.engine) == ["claude · opus · high", "codex · default", "claude · haiku · xhigh"])
        #expect(summaries.map(\.traits) == [nil, nil, "advisory · conventions"])
    }

    @Test("a Codex reviewer shows its own model and effort, and an off one says so")
    func codexOff() {
        var codex = reviewers[1]
        codex.codex.model = "gpt-5.6-luna"
        codex.codex.effort = "max"
        codex.isEnabled = false
        let summary = ReviewerSummary(codex)
        #expect(summary.engine == "codex · gpt-5.6-luna · max")
        #expect(summary.traits == "off")
    }

    @Test(
        "a reviewer that needs conventions is skipped only where there are none",
        arguments: [
            (["ref": "origin/main", "files": [], "skills": []], true),
            (["ref": "origin/main", "files": ["AGENTS.md"], "skills": []], false),
            (["ref": "origin/main", "files": [], "skills": ["adr"]], false),
            (.null, false),
        ] as [(JSONValue, Bool)])
    func skipped(conventions: JSONValue, isSkipped: Bool) throws {
        let project = try project(conventions)
        #expect(ReviewerSummary(reviewers[2], project: project).isSkipped == isSkipped)
        #expect(!ReviewerSummary(reviewers[0], project: project).isSkipped)
    }

    @Test("All repos skips nothing, and an off reviewer is off, not skipped")
    func notSkipped() throws {
        let none = try project(["ref": "origin/main", "files": [], "skills": []])
        var quality = reviewers[2]
        #expect(!ReviewerSummary(quality).isSkipped)
        quality.isEnabled = false
        #expect(!ReviewerSummary(quality, project: none).isSkipped)
    }
}
