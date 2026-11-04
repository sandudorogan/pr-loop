import PRWizardKit
import Testing

@Suite struct TodoRowTests {
    @Test("Mark Done moves back only when every row is done, and never a merged PR")
    func doneRefs() throws {
        let open = TodoRow.open(try Snapshots.item(2))
        let merged = TodoRow.done(try Snapshots.historyEntry())
        let approved = TodoRow.done(
            try Snapshots.historyEntry(["state": "settled", "key": "iprally/iprally#17121", "number": 17121]))
        #expect(![open, merged].movesBack)
        #expect([open, merged].doneRefs == [open.ref])
        #expect([merged, approved].movesBack)
        #expect([merged, approved].doneRefs == [approved.ref])
        #expect([merged].doneRefs.isEmpty)
    }

    @Test("a row speaks for its PR")
    func fields() throws {
        let mine = TodoRow.open(try Snapshots.item(0))
        #expect((mine.id, mine.author, mine.repo) == ("iprally/iprally#17190", "you", "iprally/iprally"))
        let done = TodoRow.done(try Snapshots.historyEntry())
        #expect((done.id, done.author, done.status.label) == ("iprally/iprally#17120", "colleague", "Ready"))
    }
}
