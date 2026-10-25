import Foundation
import PRWizardKit
import Testing

@Suite struct ConfigModelTests {
    static let fixtures = ["config.json", "prompt.json"]

    private static func tree(_ data: Data) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: data)
    }

    private static func reencoded<Model: Codable>(_ type: Model.Type, from data: Data) throws -> JSONValue {
        try tree(JSONEncoder().encode(JSONDecoder().decode(type, from: data)))
    }

    @Test("config.json decodes the envelope")
    func envelopeDecodes() throws {
        let envelope = try Fixture.decode(ConfigEnvelope.self, from: "config.json")
        #expect(envelope.source == .file)
        #expect(envelope.error == nil)
        #expect(envelope.realPath.hasSuffix(".pr-wizard/config.json"))
        #expect(envelope.config == envelope.defaults)
        #expect(envelope.config.review.reviewers.map(\.id) == ["opus", "codex", "quality"])
        #expect(envelope.config.fix.engine == .codex)
        #expect(envelope.config.fix.model == nil)
        #expect(envelope.config.refresh.interval == 300)
    }

    @Test("iprally's built-in gates decode in full")
    func iprallyGates() throws {
        let envelope = try Fixture.decode(ConfigEnvelope.self, from: "config.json")
        let gates = try #require(envelope.config.projects["iprally/iprally"]?.fix?.gates)
        #expect(gates.map(\.name) == ["cljfmt", "Karma"])
        #expect(gates.map(\.kind) == [.format, .test])
        let karma = gates[1]
        #expect(karma.cwd == "ui")
        #expect(karma.usesSlot == true)
        #expect(karma.timeout == 1800)
        #expect(karma.targets?.item == ["/": ".", "_": "-"])
        #expect(karma.setup?.name == "shadow-cljs compile karma-test")
        #expect(gates[0].targets == nil)
        #expect(gates[0].cwd == nil)
    }

    @Test("effective configs carry the built-in overrides and a null root without a checkout")
    func effectiveDecodes() throws {
        let envelope = try Fixture.decode(ConfigEnvelope.self, from: "config.json")
        #expect(envelope.config.projects["iprally/gitops"]?.review?.isEnabled == false)
        #expect(envelope.effective["iprally/gitops"]?.review.isEnabled == false)
        #expect(envelope.effective["iprally/gitops"]?.fix.isEnabled == true)
        #expect(envelope.effective["iprally/iprally"]?.fix.gates.count == 2)
        #expect(envelope.effective["iprally/iprally"]?.root == "/Users/sandu.dorogan/workdir/iprally")
        #expect(envelope.effective["clojure/clojurescript-site"]?.root == nil)
    }

    @Test("choices decode with the Codex default and models")
    func choicesDecode() throws {
        let choices = try Fixture.decode(ConfigEnvelope.self, from: "config.json").choices
        #expect(choices.engines == ["claude", "codex"])
        #expect(choices.codexDefault?.model == "gpt-6.1-sol")
        #expect(choices.codexDefault?.effort == "high")
        #expect(choices.codexModels.map(\.id) == ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-luna"])
        #expect(choices.codexModels.last?.efforts.contains("ultra") == false)
        #expect(choices.prompts.contains("opus.md"))
    }

    @Test("prompt.json decodes")
    func promptDecodes() throws {
        let prompt = try Fixture.decode(Prompt.self, from: "prompt.json")
        #expect(prompt.name == "merge.md")
        #expect(prompt.placeholders == ["PR", "REPO", "BASE", "FILES", "BRIEF", "SCHEMA"])
        #expect(prompt.text.contains("{FILES}"))
    }

    @Test("a fixture re-encodes to an equal JSONValue", arguments: fixtures)
    func roundTrip(name: String) throws {
        let data = try Fixture.data(name)
        let type: any Codable.Type = name == "config.json" ? ConfigEnvelope.self : Prompt.self
        func check<Model: Codable>(_: Model.Type) throws {
            #expect(try Self.reencoded(Model.self, from: data) == Self.tree(data))
        }
        try check(type)
    }

    @Test("unknown keys survive in reviewers and gates, where arrays replace whole")
    func unknownKeysKept() throws {
        let reviewerJSON = """
            {"id": "x", "enabled": true, "label": "X", "prompt": "opus.md", "engine": "claude", "fallback": true,
             "needs_conventions": false, "advisory": false, "extra": 1,
             "claude": {"model": "opus", "effort": null, "incremental": {"model": "opus", "effort": null, "n": 2}, "k": 3},
             "codex": {"model": null, "effort": null, "c": 4}}
            """
        let gateJSON = """
            {"name": "g", "kind": "test", "when": ["*"], "run": "r", "g": 5, "targets": {"keep": "k", "t": 6},
             "setup": {"name": "s", "run": "r", "s": 7}}
            """
        let reviewer = try JSONDecoder().decode(ReviewerConfig.self, from: Data(reviewerJSON.utf8))
        #expect(reviewer.unknown == ["extra": .number(1)])
        #expect(reviewer.claude.unknown == ["k": .number(3)])
        #expect(reviewer.claude.incremental?.unknown == ["n": .number(2)])
        #expect(reviewer.codex.unknown == ["c": .number(4)])
        let gate = try JSONDecoder().decode(GateConfig.self, from: Data(gateJSON.utf8))
        #expect(gate.unknown == ["g": .number(5)])
        #expect(gate.targets?.unknown == ["t": .number(6)])
        #expect(gate.setup?.unknown == ["s": .number(7)])
        #expect(
            try Self.reencoded(ReviewerConfig.self, from: Data(reviewerJSON.utf8)) == Self.tree(Data(reviewerJSON.utf8))
        )
        #expect(try Self.reencoded(GateConfig.self, from: Data(gateJSON.utf8)) == Self.tree(Data(gateJSON.utf8)))
    }

    @Test("an unknown key elsewhere in the config does not fail the decode")
    func unknownKeysTolerated() throws {
        let text = String(decoding: try Fixture.data("config.json"), as: UTF8.self)
        let future = text.replacing(#""version": 1,"#, with: #""version": 1, "future": true,"#)
        #expect(future != text)
        let envelope = try JSONDecoder().decode(ConfigEnvelope.self, from: Data(future.utf8))
        #expect(envelope.config.version == 1)
    }

    @Test("a reviewer without the optional keys gets the daemon's defaults")
    func reviewerDefaults() throws {
        let json = #"{"id": "x", "label": "X", "prompt": "opus.md", "engine": "grok"}"#
        let reviewer = try JSONDecoder().decode(ReviewerConfig.self, from: Data(json.utf8))
        #expect(reviewer.engine == .unknown("grok"))
        #expect(reviewer.isEnabled && reviewer.hasFallback)
        #expect(!reviewer.needsConventions && !reviewer.isAdvisory)
        #expect(reviewer.claude.model == nil)
    }
}
