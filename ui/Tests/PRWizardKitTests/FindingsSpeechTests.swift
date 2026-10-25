import Foundation
import PRWizardKit
import Testing

@Suite struct FindingsSpeechTests {
    @Test("reads counts per reviewer, the floor of an older head and the top finding")
    func stale() throws {
        let speech = FindingsSpeech(try #require(try Snapshots.item(0).findings))
        #expect(
            speech.findings
                == "Claude Opus 5.5, Findings: 1 high, 1 medium; Codex, Findings: 2 medium; "
                + "Claude Haiku 5.5 · quality self-review, Clean")
        #expect(speech.atFloor == "4, from an older head")
        #expect(
            speech.topFinding
                == "high, Filters reset when the route params change, ui/src/cljs/iprally_ui/search/events.cljs:57")
    }

    @Test("reads a current digest")
    func current() throws {
        let speech = FindingsSpeech(try #require(try Snapshots.item(2).findings))
        #expect(
            speech.findings
                == "Claude Opus 5.5, Clean; Codex, Clean; Claude Haiku 5.5 · quality self-review, Findings: 2 medium, 1 low"
        )
        #expect(speech.atFloor == "2")
        #expect(speech.topFinding?.hasPrefix("medium, Sub reads app-db with a get-in path") == true)
    }

    @Test("says none for an empty digest")
    func empty() throws {
        let digest = """
            {"head": "9f8e7d6c5b4a", "current": true, "round": 1, "at_floor": 0,
             "conventions": [], "top": [], "reviewers": []}
            """
        let speech = FindingsSpeech(try JSONDecoder.daemon.decode(Findings.self, from: Data(digest.utf8)))
        #expect(speech.findings == "None")
        #expect(speech.atFloor == "None")
        #expect(speech.topFinding == nil)
    }

    @Test(
        "truncates the conventions footer after three files",
        arguments: [
            ([], "No project conventions"),
            (["AGENTS.md", "CLAUDE.md", "ui/AGENTS.md"], "Followed AGENTS.md · CLAUDE.md · ui/AGENTS.md"),
            (
                ["AGENTS.md", "CLAUDE.md", "ui/AGENTS.md", "ui/CLAUDE.md", ".clj-kondo/config.edn"],
                "Followed AGENTS.md · CLAUDE.md · ui/AGENTS.md +2"
            ),
        ])
    func footer(files: [String], line: String) throws {
        let patch: JSONValue = .object([
            "head": .string("9f8e7d6c5b4a"), "current": .bool(true), "round": .number(1), "at_floor": .number(0),
            "conventions": .array(files.map(JSONValue.string)), "top": .array([]), "reviewers": .array([]),
        ])
        let findings = try #require(try Snapshots.item(2, ["findings": patch]).findings)
        #expect(findings.conventionsFooter == line)
    }
}
