import Foundation
import PRWizardKit
import Testing

@Suite struct OverrideResolverTests {
    struct Oracle: Decodable {
        struct Case: Decodable {
            let config: Int
            let repo: String
            let effective: JSONValue
        }

        let configs: [JSONValue]
        let effective: [Case]
    }

    static let oracle = Result { try JSONDecoder().decode(Oracle.self, from: Fixture.oracle()) }
    static let repos = ["iprally/iprally", "iprally/gitops", "sandudorogan/dataspex", "clojure/clojurescript-site"]

    private let resolver = OverrideResolver(config: [
        "review": ["enabled": true, "trivial": ["*.md"]],
        "fix": ["model": "gpt-6-astra", "workers": 3],
        "projects": ["iprally/gitops": ["review": ["enabled": false], "fix": ["model": .null]]],
    ])

    private func resolved(_ key: String, in scope: SettingsScope) -> (JSONValue, OverrideResolver.Source) {
        let resolved = resolver.resolve(key, in: scope)
        return (resolved.value, resolved.source)
    }

    @Test("resolves like pr_wizard.config.effective", arguments: 0..<10)
    func matchesDaemon(index: Int) throws {
        let oracle = try Self.oracle.get()
        let vector = oracle.effective[index]
        let resolver = OverrideResolver(config: oracle.configs[vector.config])
        for lane in ["review", "fix"] {
            #expect(resolver.resolve(lane, in: .project(vector.repo)).value == vector.effective[[lane]])
        }
    }

    @Test("resolves config.json to its own effective block", arguments: repos)
    func matchesEnvelope(repo: String) throws {
        let envelope = try Fixture.decode(ConfigEnvelope.self, from: "config.json")
        let resolver = OverrideResolver(config: try JSONValue(encoding: envelope.config))
        let effective = try #require(envelope.effective[repo])
        #expect(resolver.resolve("review", in: .project(repo)).value == (try JSONValue(encoding: effective.review)))
        #expect(resolver.resolve("fix", in: .project(repo)).value == (try JSONValue(encoding: effective.fix)))
    }

    @Test("an overridden key comes from the project")
    func overridden() {
        #expect(resolved("review.enabled", in: .project("iprally/gitops")) == (false, .project("iprally/gitops")))
    }

    @Test("an unset key inherits the default")
    func inherited() {
        #expect(resolved("fix.workers", in: .project("iprally/gitops")) == (3, .defaults))
        #expect(resolver.resolve("review.enabled", in: .project("acme/new")).source == .defaults)
        #expect(resolved("review.enabled", in: .allRepos) == (true, .defaults))
    }

    @Test("an explicit null override wins over the default")
    func explicitNull() {
        #expect(resolved("fix.model", in: .project("iprally/gitops")) == (.null, .project("iprally/gitops")))
    }

    @Test("isOverridden reads the source")
    func isOverridden() {
        #expect(resolver.isOverridden("review.enabled", in: .project("iprally/gitops")))
        #expect(!resolver.isOverridden("review.trivial", in: .project("iprally/gitops")))
        #expect(!resolver.isOverridden("review.enabled", in: .allRepos))
    }

    @Test("counts the overridden keys of a project")
    func overrideCount() {
        #expect(resolver.overrideCount(in: "iprally/gitops") == 2)
        #expect(resolver.overrideCount(in: "acme/new") == 0)
    }
}
