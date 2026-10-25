import PRWizardKit
import Testing

@MainActor @Suite struct PeekModelTests {
    private let gate = Gate()
    private let sleeper: Sleeper
    private let peek: PeekModel

    init() {
        sleeper = Sleeper(gate: gate)
        peek = PeekModel(sleep: sleeper.sleep)
    }

    private func elapse() async {
        await gate.arrival()
        await gate.open()
    }

    private func stays(_ phase: PeekModel.Phase, in peek: PeekModel? = nil) async -> Bool {
        let peek = peek ?? self.peek
        return await !eventually { peek.phase != phase }
    }

    @Test("shows after the dwell")
    func dwell() async {
        peek.enter("a")
        #expect(peek.phase == .dwelling("a"))
        #expect(peek.shownID == nil)
        await elapse()
        #expect(await eventually { peek.phase == .shown("a") })
        #expect(peek.shownID == "a")
        #expect(await sleeper.durations == [PeekModel.dwell])
    }

    @Test("leaving during the dwell shows nothing")
    func cancelDwell() async {
        peek.enter("a")
        await gate.arrival()
        peek.exit("a")
        #expect(peek.phase == .idle)
        await gate.open()
        #expect(await stays(.idle))
    }

    @Test("Space toggles the one selected row and leaves every other Space alone")
    func space() {
        #expect(!peek.toggleOnSpace(nil))
        #expect(peek.phase == .idle)
        #expect(peek.toggleOnSpace("a"))
        #expect(peek.phase == .shown("a"))
        #expect(peek.toggleOnSpace("a"))
        #expect(peek.phase == .idle)
    }

    @Test("hides after the grace once the pointer leaves")
    func leave() async {
        peek.toggle("a")
        peek.exit("a")
        #expect(peek.phase == .leaving("a"))
        #expect(peek.shownID == "a")
        await elapse()
        #expect(await eventually { peek.phase == .idle })
        #expect(await sleeper.durations == [PeekModel.grace])
    }

    @Test("coming back within the grace keeps it shown")
    func comeBack() async {
        peek.toggle("a")
        peek.exit("a")
        await gate.arrival()
        peek.enter("a")
        #expect(peek.phase == .shown("a"))
        await gate.open()
        #expect(await stays(.shown("a")))
    }

    @Test("another row replaces the shown one and dwells")
    func oneAtATime() async {
        let peek = PeekModel(sleep: Sleeper().sleep)
        peek.toggle("a")
        peek.exit("a")
        peek.enter("b")
        #expect(peek.phase == .dwelling("b"))
        #expect(await eventually { peek.phase == .shown("b") })
        #expect(await stays(.shown("b"), in: peek))
    }

    @Test("re-entering the dwelling row keeps the running dwell")
    func reenterDwell() async {
        peek.enter("a")
        peek.enter("a")
        await elapse()
        #expect(await eventually { peek.phase == .shown("a") })
        #expect(await sleeper.durations == [PeekModel.dwell])
    }

    @Test("an exit from another row changes nothing")
    func foreignExit() {
        peek.enter("a")
        peek.exit("b")
        #expect(peek.phase == .dwelling("a"))
        peek.toggle("a")
        peek.exit("b")
        #expect(peek.phase == .shown("a"))
    }

    @Test("toggles at once, with no dwell")
    func toggle() async {
        peek.toggle("a")
        #expect(peek.phase == .shown("a"))
        peek.toggle("b")
        #expect(peek.phase == .shown("b"))
        peek.toggle("b")
        #expect(peek.phase == .idle)
        #expect(await sleeper.durations.isEmpty)
    }

    @Test("dismiss cancels a dwell")
    func dismiss() async {
        peek.enter("a")
        await gate.arrival()
        peek.dismiss()
        await gate.open()
        #expect(await stays(.idle))
    }
}
