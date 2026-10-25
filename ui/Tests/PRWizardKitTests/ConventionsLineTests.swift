import PRWizardKit
import Testing

@Suite struct ConventionsLineTests {
    private func project(_ repo: String) throws -> Project {
        try #require(try Fixture.decode(QueueSnapshot.self, from: "queue.json").projects.first { $0.repo == repo })
    }

    @Test("All repos names what every repo follows")
    func allRepos() throws {
        let line = try #require(ConventionsLine(.allRepos, project: nil))
        #expect(line.rows.isEmpty)
        #expect(line.sentence?.hasPrefix("Each repo's own AGENTS.md, CLAUDE.md") == true)
    }

    @Test("a long list shows three and keeps the rest for the tooltip")
    func truncates() throws {
        let line = try #require(ConventionsLine(.project("iprally/iprally"), project: try project("iprally/iprally")))
        #expect(line.ref == "origin/main")
        #expect(line.rows.map(\.title) == ["Follows", "Skills"])
        #expect(line.rows[0].shown == ["AGENTS.md", "CLAUDE.md", "api/AGENTS.md"])
        #expect(line.rows[0].hidden == ["api/CLAUDE.md", "ui/AGENTS.md", "ui/CLAUDE.md", ".clj-kondo/config.edn"])
        #expect(line.rows[1].hidden.isEmpty)
    }

    @Test("no skills, no Skills row")
    func noSkills() throws {
        let line = try #require(ConventionsLine(.project("iprally/gitops"), project: try project("iprally/gitops")))
        #expect(line.rows.map(\.title) == ["Follows"])
        #expect(line.rows[0].shown == ["CLAUDE.md"])
    }

    @Test(
        "no files reads as a sentence, with the reviewers it skips",
        arguments: [
            ([], "Follows nothing documented."),
            (["quality"], "Follows nothing documented. The quality reviewer is skipped here (no-conventions)."),
            (
                ["quality", "style", "docs"],
                "Follows nothing documented. The quality, style and docs reviewers are skipped here (no-conventions)."
            ),
        ])
    func none(skipped: [String], sentence: String) throws {
        let repo = "sandudorogan/dataspex"
        let line = try #require(ConventionsLine(.project(repo), project: try project(repo), skipped: skipped))
        #expect(line.rows.isEmpty)
        #expect(line.sentence == sentence)
    }

    @Test(
        "skills without files read as a sentence that names the skills, which the daemon still runs",
        arguments: [
            (["adr"], "Follows 1 skill: adr"),
            (["add-phosphor-icon", "adr", "quality"], "Follows 3 skills: add-phosphor-icon, adr, quality"),
            (["a", "b", "c", "d", "e"], "Follows 5 skills: a, b, c, …"),
        ])
    func skillsOnly(skills: [String], sentence: String) throws {
        let patch: [String: JSONValue] = [
            "conventions": ["ref": "origin/main", "files": [], "skills": .array(skills.map(JSONValue.string))]
        ]
        let line = try #require(
            ConventionsLine(.project("sandudorogan/dataspex"), project: try Snapshots.project(2, patch)))
        #expect(line.rows.isEmpty)
        #expect(line.sentence == sentence)
    }

    @Test("no checkout, no line")
    func noCheckout() throws {
        let repo = "clojure/clojurescript-site"
        #expect(ConventionsLine(.project(repo), project: try project(repo)) == nil)
    }
}
