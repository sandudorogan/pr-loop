import PRWizardKit
import Testing

@Suite struct ActionAvailabilityTests {
    private let live = 0
    private let queued = 1
    private let ready = 2
    private let gitops = 3
    private let site: [String: JSONValue] = ["repo": .string("clojure/clojurescript-site")]

    private func projects() throws -> [Project] {
        try Snapshots.queue().projects
    }

    @Test("move to front takes queued and waiting PRs that no run holds")
    func moveToFront() throws {
        #expect(ActionAvailability.moveToFront(try Snapshots.item(live)) == .unavailable("In a live run"))
        #expect(ActionAvailability.moveToFront(try Snapshots.item(queued)) == .available)
        #expect(
            ActionAvailability.moveToFront(try Snapshots.item(ready)) == .unavailable("Only queued or waiting PRs move")
        )
        #expect(ActionAvailability.moveToFront(try Snapshots.item(gitops)) == .available)
    }

    @Test("review now needs a checkout and the review lane")
    func review() throws {
        let projects = try projects()
        #expect(ActionAvailability.review(try Snapshots.item(live), in: projects) == .unavailable("In a live run"))
        #expect(ActionAvailability.review(try Snapshots.item(queued), in: projects) == .available)
        #expect(
            ActionAvailability.review(try Snapshots.item(gitops), in: projects)
                == .unavailable("The review lane is off for iprally/gitops"))
        #expect(
            ActionAvailability.review(try Snapshots.item(queued, site), in: projects)
                == .unavailable("No usable checkout of clojure/clojurescript-site"))
    }

    @Test("retry fix needs my PR, no opt-out label, a checkout and the fix lane")
    func fix() throws {
        let projects = try projects()
        let fixOff = [try Snapshots.project(1, ["fix": .bool(false)])]
        #expect(ActionAvailability.fix(try Snapshots.item(gitops), in: projects) == .available)
        #expect(ActionAvailability.fix(try Snapshots.item(live), in: projects) == .unavailable("In a live run"))
        #expect(
            ActionAvailability.fix(try Snapshots.item(queued), in: projects)
                == .unavailable("Only your own PRs get fixes"))
        #expect(
            ActionAvailability.fix(
                try Snapshots.item(gitops, ["labels": .array([.string("no-auto-fix")])]), in: projects)
                == .unavailable("Labeled no-auto-fix"))
        #expect(
            ActionAvailability.fix(try Snapshots.item(gitops, site), in: projects)
                == .unavailable("No usable checkout of clojure/clojurescript-site"))
        #expect(
            ActionAvailability.fix(try Snapshots.item(gitops), in: fixOff)
                == .unavailable("The fix lane is off for iprally/gitops"))
    }

    @Test("a selection is available only when every PR in it is")
    func all() {
        #expect(ActionAvailability.all([.available, .available]) == .available)
        #expect(ActionAvailability.all([.available, .unavailable("a"), .unavailable("b")]) == .unavailable("a"))
        #expect(ActionAvailability.unavailable("a").reason == "a")
        #expect(ActionAvailability.available.reason == nil)
    }
}
