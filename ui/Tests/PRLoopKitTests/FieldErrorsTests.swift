import PRLoopKit
import Testing

@Suite struct FieldErrorsTests {
    private let gitops = SettingsScope.project("iprally/gitops")

    private func errors() throws -> FieldErrors {
        FieldErrors(try Fixture.decode(APIErrorBody.self, from: "error-invalid-config.json").error.details ?? [])
    }

    @Test("a default path maps to All repos")
    func allRepos() throws {
        #expect(try errors().messages(at: "review.workers", in: .allRepos) == ["must be an integer from 1 to 8"])
        #expect(try errors().messages(at: "review.workers", in: gitops).isEmpty)
    }

    @Test("a projects[\"…\"] path maps to that project's key")
    func project() throws {
        #expect(try errors().messages(at: "fix.workers", in: gitops) == ["must be an integer from 1 to 8"])
        #expect(try errors().messages(at: "fix.workers", in: .allRepos).isEmpty)
    }

    @Test("contains names the scopes with problems, for the dropdown badge")
    func contains() throws {
        #expect(try errors().contains(gitops))
        #expect(try errors().contains(.allRepos))
        #expect(try !errors().contains(.project("iprally/iprally")))
    }

    @Test("problems no shown field claims go to the banner")
    func unclaimed() throws {
        #expect(try errors().unclaimed(in: gitops, by: ["fix.workers"]).isEmpty)
        #expect(try errors().unclaimed(in: gitops, by: ["fix.enabled"]).map(\.path) == [gitops.path(of: "fix.workers")])
        #expect(try errors().unclaimed(in: .allRepos, by: ["review"]).isEmpty)
    }

    @Test("scope paths round-trip, a dotted repo name included")
    func paths() {
        #expect(
            SettingsScope.project("acme/site.js").path(of: "review.reviewers[1].engine")
                == "projects[\"acme/site.js\"].review.reviewers[1].engine")
        #expect(SettingsScope(rawValue: "") == .allRepos)
        #expect(SettingsScope(rawValue: "iprally/gitops") == gitops)
        #expect(gitops.rawValue == "iprally/gitops")
    }
}
