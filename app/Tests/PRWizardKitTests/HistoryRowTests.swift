import PRWizardKit
import Testing

@Suite struct HistoryRowTests {
    @Test(
        "reads the state as a label, unknown values capitalized",
        arguments: [("settled", "Open"), ("merged", "Merged"), ("closed", "Closed"), ("abandoned", "Abandoned")])
    func state(raw: String, label: String) throws {
        let row = HistoryRow(try Snapshots.historyEntry(["state": .string(raw)]))
        #expect(row.stateLabel == label)
    }

    @Test(
        "styles the outcome with the status vocabulary",
        arguments: [
            ("approved", Tone.good, "Approved"), ("ready", .good, "Ready"), ("tests-red", .bad, "Tests red"),
            ("pushed", .info, "Pushed"), ("rebasing", .neutral, "rebasing"),
        ])
    func outcome(raw: String, tone: Tone, label: String) throws {
        let style = HistoryRow(try Snapshots.historyEntry(["outcome": .string(raw)])).outcome
        #expect((style.tone, style.label) == (tone, label))
    }

    @Test("the row id is the wire key")
    func identity() throws {
        let entry = try Snapshots.historyEntry()
        #expect(HistoryRow(entry).id == "iprally/iprally#17120")
    }
}
