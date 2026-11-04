import PRLoopKit
import Testing

@Suite struct EffortChoicesTests {
    private let choices: Choices

    init() throws {
        choices = try Settings.envelope().choices
    }

    @Test("a listed model narrows the efforts to its own")
    func narrows() {
        #expect(
            EffortChoices(choices, model: "gpt-5.6-luna", effort: nil).efforts == [
                "low", "medium", "high", "xhigh", "max",
            ])
    }

    @Test(
        "an unlisted model, or the unlisted Codex default, offers every Codex effort",
        arguments: [
            "gpt-6.1-sol", "my-model", nil,
        ])
    func unlisted(model: String?) {
        #expect(EffortChoices(choices, model: model, effort: nil).efforts == choices.codexEfforts)
    }

    @Test("the current effort stays offered when the model does not list it")
    func keepsCurrent() {
        #expect(EffortChoices(choices, model: "gpt-5.6-luna", effort: "ultra").efforts.last == "ultra")
        #expect(EffortChoices(choices, model: "gpt-6-astra", effort: "ultra").efforts.count == 6)
    }

    @Test("null reads as the Codex default")
    func defaults() throws {
        #expect(EffortChoices(choices, model: nil, effort: nil).defaultLabel == "Codex default (high)")
        #expect(choices.codexModelLabel == "Codex default (gpt-6.1-sol)")
        let unknown = try Settings.envelope(merging: ["choices": ["codex_default": .null]]).choices
        #expect(EffortChoices(unknown, model: nil, effort: nil).defaultLabel == "Codex default")
        #expect(unknown.codexModelLabel == "Codex default")
    }
}
