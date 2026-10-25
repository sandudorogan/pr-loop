import Foundation
import PRWizardKit
import Testing

@Suite struct ResponseModelTests {
    @Test("events.json decodes both event types")
    func eventsDecode() throws {
        let page = try Fixture.decode(EventPage.self, from: "events.json")
        #expect(page.cursor == "k3f9a2.58")
        #expect(page.isReset == false)
        #expect(page.events.map(\.type) == [.readyForApproval, .readyWithdrawn])
        #expect(page.events.map(\.verdict) == [.qualityOnly, nil])
        #expect(page.events.first?.ref == PRRef(repo: "iprally/iprally", number: 17166))
    }

    @Test("history.json decodes an entry with its digest")
    func historyDecodes() throws {
        let entry = try #require(Fixture.decode(HistoryPage.self, from: "history.json").entries.first)
        #expect(entry.state == .merged)
        #expect(entry.fixesPushed == 0)
        #expect(entry.closedAt != nil)
        #expect(entry.findings?.reviewers.map(\.result) == [.clean, .clean, .notesOnly])
    }

    @Test("next.json decodes bump results")
    func nextDecodes() throws {
        let result = try Fixture.decode(NextResult.self, from: "next.json")
        #expect(result.next.first == "iprally/iprally#17201")
        #expect(result.results.map(\.isBumped) == [true, false])
        #expect(result.results.map(\.reason) == [nil, "active"])
    }

    @Test("action fixtures decode")
    func actionsDecode() throws {
        #expect(try Fixture.decode(Accepted.self, from: "accepted.json").key == "iprally/iprally#17190")
        #expect(try Fixture.decode(PauseState.self, from: "paused.json").isPaused)
    }

    @Test("error bodies decode with and without details")
    func errorsDecode() throws {
        let invalid = try Fixture.decode(APIErrorBody.self, from: "error-invalid-config.json")
        let busy = try Fixture.decode(APIErrorBody.self, from: "error-busy.json")
        #expect(invalid.error.code == "invalid_config")
        #expect(invalid.error.details?.map(\.path) == ["review.workers", #"projects["iprally/gitops"].fix.workers"#])
        #expect(busy.error.code == "busy")
        #expect(busy.error.details == nil)
    }

    @Test(
        "JSONValue round-trips every fixture",
        arguments: try FileManager.default.contentsOfDirectory(atPath: Fixture.directory.path()).sorted())
    func jsonValueRoundTrip(name: String) throws {
        let value = try JSONDecoder().decode(JSONValue.self, from: Fixture.data(name))
        let again = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value))
        #expect(again == value)
    }
}
