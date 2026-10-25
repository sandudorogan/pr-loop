import PRWizardKit
import Testing

@MainActor @Suite struct PeekModelTests {
    private let peek = PeekModel()

    @Test("Space toggles the one selected row and leaves every other Space alone")
    func space() {
        #expect(!peek.toggleOnSpace(nil))
        #expect(peek.shownID == nil)
        #expect(peek.toggleOnSpace("a"))
        #expect(peek.shownID == "a")
        #expect(peek.toggleOnSpace("a"))
        #expect(peek.shownID == nil)
    }

    @Test("toggles one row at a time")
    func toggle() {
        peek.toggle("a")
        #expect(peek.shownID == "a")
        peek.toggle("b")
        #expect(peek.shownID == "b")
        peek.toggle("b")
        #expect(peek.shownID == nil)
    }

    @Test("dismiss hides the shown row")
    func dismiss() {
        peek.toggle("a")
        peek.dismiss()
        #expect(peek.shownID == nil)
    }
}
