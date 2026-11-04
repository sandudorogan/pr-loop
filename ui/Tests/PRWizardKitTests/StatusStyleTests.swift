import PRWizardKit
import Testing

@Suite struct StatusStyleTests {
    @Test(
        "maps every status to a symbol, a tone and a label",
        arguments: [
            ("reviewing", "eye", Tone.working, "Reviewing"),
            ("fixing", "hammer", .working, "Fixing"),
            ("queued", "clock", .neutral, "Queued"),
            ("ready", "checkmark.seal.fill", .good, "Ready"),
            ("done", "checkmark.circle.fill", .neutral, "Done"),
            ("approved", "checkmark.seal.fill", .good, "Approved"),
            ("clean", "checkmark.seal.fill", .good, "Clean"),
            ("quality-only", "checkmark.seal.fill", .good, "Notes only"),
            ("posted", "text.bubble", .info, "Findings posted"),
            ("held", "pause.circle", .neutral, "Held"),
            ("needs-human", "person.fill.questionmark", .attention, "Needs you"),
            ("too-big", "person.fill.questionmark", .attention, "Too big"),
            ("failed", "xmark.octagon", .bad, "Failed"),
            ("limited", "hourglass", .attention, "Usage limit"),
            ("skipped", "minus.circle", .neutral, "Skipped"),
            ("unchanged", "minus.circle", .neutral, "Unchanged"),
            ("trivial", "minus.circle", .neutral, "Trivial"),
            ("baseline", "minus.circle", .neutral, "Baseline"),
            ("new", "minus.circle", .neutral, "New"),
            ("pushed", "arrow.up.circle", .info, "Pushed"),
            ("tests-red", "xmark.octagon", .bad, "Tests red"),
            ("error", "xmark.octagon", .bad, "Error"),
            ("ci-stuck", "exclamationmark.triangle", .attention, "CI stuck"),
            ("nothing-to-fix", "checkmark.circle", .good, "Nothing to fix"),
            ("refuted-only", "checkmark.circle", .good, "Refuted only"),
            ("no-changes", "checkmark.circle", .good, "No changes"),
            ("rebasing", "questionmark.circle", .neutral, "rebasing"),
        ])
    func style(status: String, symbol: String, tone: Tone, label: String) {
        let style = StatusStyle(status)
        #expect((style.symbol, style.tone, style.label) == (symbol, tone, label))
    }

    @Test(
        "a ready PR says who acts next",
        arguments: [(true, Tone.mine, "Ready for review"), (false, .good, "Ready to approve")])
    func ready(mine: Bool, tone: Tone, label: String) throws {
        let style = StatusStyle(try Snapshots.item(2, ["mine": .bool(mine)]))
        #expect((style.tone, style.label) == (tone, label))
    }
}
