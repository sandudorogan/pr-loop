import PRWizardKit
import Testing

@MainActor @Suite struct LanesLayoutTests {
    private func layout(
        _ scope: SettingsScope, separate: Bool, patch: [String: JSONValue] = [:], review: Bool = true,
        fix: Bool = true
    ) throws -> LanesLayout {
        LanesLayout(
            scope: scope, isSeparate: separate,
            project: try Snapshots.project(1, patch),
            isReviewOn: review, isFixOn: fix)
    }

    @Test("All repos shows the global rows, and the totals only with separate lanes")
    func allRepos() throws {
        let shared = try layout(.allRepos, separate: false)
        #expect(shared.isGlobal && !shared.showsTotals)
        #expect((shared.reviewTitle, shared.fixTitle) == ("Parallel reviews", "Parallel fix passes"))
        #expect((shared.review, shared.fix, shared.sharedNote) == (.stepper, .stepper, nil))
        let separate = try layout(.allRepos, separate: true)
        #expect(separate.isGlobal && separate.showsTotals)
        #expect((separate.reviewTitle, separate.fixTitle) == ("Reviews per repo", "Fix passes per repo"))
    }

    @Test("a project hides the global rows")
    func project() throws {
        let layout = try layout(Settings.gitops, separate: true)
        #expect(!layout.isGlobal && !layout.showsTotals)
        #expect((layout.reviewTitle, layout.fixTitle) == ("Reviews", "Fix passes"))
    }

    @Test(
        "a project's worker rows follow separate, its lanes and its status",
        arguments: [
            (true, true, true, "active", LanesLayout.Workers.stepper, LanesLayout.Workers.stepper),
            (true, false, true, "active", .laneOff, .stepper),
            (true, true, false, "off", .stepper, .laneOff),
            (true, false, false, "off", .laneOff, .laneOff),
            (false, true, true, "active", .sharedPool, .sharedPool),
            (false, false, true, "active", .laneOff, .sharedPool),
            (false, true, false, "active", .sharedPool, .laneOff),
            (true, true, true, "error", .unavailable, .unavailable),
            (false, true, true, "no-checkout", .unavailable, .unavailable),
        ])
    func workerRows(
        separate: Bool, review: Bool, fix: Bool, status: String, expectedReview: LanesLayout.Workers,
        expectedFix: LanesLayout.Workers
    ) throws {
        let isAvailable = ["active", "off"].contains(status)
        let layout = try layout(
            Settings.gitops, separate: separate, patch: ["status": .string(status), "available": .bool(isAvailable)],
            review: review, fix: fix)
        #expect(layout.review == expectedReview)
        #expect(layout.fix == expectedFix)
    }

    @Test("one line names the pools a project shares")
    func sharedNote() throws {
        #expect(
            try layout(Settings.gitops, separate: false).sharedNote
                == "Shares the review and fix pools with every repo.")
        #expect(
            try layout(Settings.gitops, separate: false, review: false).sharedNote
                == "Shares the fix pool with every repo.")
        #expect(
            try layout(Settings.gitops, separate: false, fix: false).sharedNote
                == "Shares the review pool with every repo.")
        #expect(try layout(Settings.gitops, separate: true).sharedNote == nil)
    }
}
