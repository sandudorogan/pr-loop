import PRLoopKit
import Testing

@Suite struct QueueLayoutTests {
    @Test("a dragged section takes the place of the one it lands on")
    func section() {
        var layout = QueueLayout()
        let moved = layout.drop("section:done", on: "section:toApprove")
        #expect(moved)
        #expect(layout.sectionOrder == [.done, .toApprove, .mine])
        layout.drop("section:toApprove", on: "section:mine")
        #expect(layout.sectionOrder == [.done, .mine, .toApprove])
    }

    @Test("a stage moves inside its own section only")
    func stage() {
        var layout = QueueLayout()
        let moved = layout.drop("stage:mine.waiting", on: "stage:mine.ready")
        #expect(moved)
        #expect(layout.stageOrder(of: .mine) == [.waiting, .ready, .active, .queued, .paused])
        #expect(layout.stageOrder(of: .toApprove) == [.ready, .active, .queued, .waiting, .paused])
        let acrossSections = layout.drop("stage:mine.ready", on: "stage:toApprove.paused")
        #expect(!acrossSections)
        let ontoASection = layout.drop("stage:mine.ready", on: "section:mine")
        #expect(!ontoASection)
        let notAHeader = layout.drop("#17166", on: "stage:mine.ready")
        #expect(!notAHeader)
    }

    @Test("the layout round-trips through its stored JSON, and a short one fills in the rest")
    func stored() throws {
        var layout = QueueLayout()
        layout.drop("section:mine", on: "section:toApprove")
        layout.drop("stage:toApprove.paused", on: "stage:toApprove.ready")
        #expect(QueueLayout(rawValue: layout.rawValue) == layout)
        let short = try #require(QueueLayout(rawValue: #"{"sections": ["done"], "stages": []}"#))
        #expect(short.sectionOrder == [.done, .toApprove, .mine])
        #expect(QueueLayout(rawValue: "nonsense") == nil)
    }

    @Test("sections and stages follow the layout")
    func sections() throws {
        var layout = QueueLayout()
        layout.drop("section:mine", on: "section:toApprove")
        layout.drop("stage:toApprove.queued", on: "stage:toApprove.ready")
        let sections = QueueFilter().sections(try Snapshots.queue().items, layout: layout)
        #expect(sections.map(\.kind) == [.mine, .toApprove])
        #expect(
            sections.map { $0.stages.map(\.style.label) } == [
                ["In work", "Waiting"], ["Up next", "Ready to approve"],
            ])
    }
}
