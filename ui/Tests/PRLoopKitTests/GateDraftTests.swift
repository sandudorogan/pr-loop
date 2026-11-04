import Foundation
import PRLoopKit
import Testing

@Suite struct GateDraftTests {
    private func iprally() throws -> [JSONValue] {
        let config = try Settings.envelope().rawConfig
        guard case .array(let gates) = config[["projects", "iprally/iprally", "fix", "gates"]] else { return [] }
        return gates
    }

    private func draft(_ edit: (inout GateDraft) -> Void = { _ in }) -> GateDraft {
        var draft = GateDraft()
        draft.name = "fmt"
        draft.when = ["*.clj"]
        draft.run = "cljfmt fix {files}"
        edit(&draft)
        return draft
    }

    @Test("iprally's cljfmt and Karma gates round-trip as the same JSON")
    func roundTrip() throws {
        let gates = try iprally()
        #expect(gates.count == 2)
        for gate in gates {
            let config = try gate.decoded(GateConfig.self)
            #expect(try JSONValue(encoding: GateDraft(config).gate) == gate)
        }
    }

    @Test("chained item replacements keep their order through decode, edit and encode", arguments: [false, true])
    func itemOrder(reversed: Bool) throws {
        let pairs = reversed ? #""b":"c","a":"b""# : #""a":"b","b":"c""#
        let text = #"{"name":"t","kind":"test","when":["*"],"run":"x {item}","targets":{"item":{\#(pairs)}}}"#
        var draft = GateDraft(try JSONValue(parsing: Data(text.utf8)).decoded(GateConfig.self))
        #expect(draft.targetItems.map(\.from) == (reversed ? ["b", "a"] : ["a", "b"]))
        draft.name = "t2"
        draft.targetItems.append(.init(from: "c", to: "d"))
        var list = GateList(.array([]))
        list.save(draft.gate, at: nil)
        let wire = String(decoding: list.value.data, as: UTF8.self)
        #expect(wire.contains(#""item":{\#(pairs),"c":"d"}"#))
    }

    @Test("a key the app does not know survives an edit")
    func unknownKeys() throws {
        let tree = JSONValue.merged(
            try iprally()[1], ["retries": 4, "targets": ["cache": true], "setup": ["shell": "zsh"]])
        var draft = GateDraft(try tree.decoded(GateConfig.self))
        draft.name = "Karma 2"
        let saved = try JSONValue(encoding: draft.gate)
        #expect(saved[["retries"]] == 4)
        #expect(saved[["targets", "cache"]] == true)
        #expect(saved[["setup", "shell"]] == "zsh")
        #expect(saved[["name"]] == "Karma 2")
    }

    @Test("blank text leaves its key out, and a blank pair row is dropped")
    func blanks() throws {
        let saved = try JSONValue(
            encoding: draft {
                $0.cwd = "  "
                $0.needs = ["", " "]
                $0.hasTargets = true
                $0.targetItems = [.init()]
            }.gate)
        #expect(
            saved == ["name": "fmt", "kind": "format", "when": ["*.clj"], "run": "cljfmt fix {files}", "targets": [:]])
    }

    @Test("a new gate is a format gate that still needs its fields")
    func empty() {
        let paths = GateDraft().problems.map(\.path)
        #expect(paths == ["name", "when", "run"])
        #expect(draft().isValid)
    }

    @Test(
        "a regex that Python compiles passes, one it rejects gets a caption",
        arguments: [
            (#"^ui/test/(.+_test)\.cljs$"#, true), (#"(?P<ns>[\w.-]+)"#, true), (#"(a)(?P=x)"#, false),
            ("(unclosed", false), ("[a-", false), ("*oops", false),
        ])
    func regex(pattern: String, compiles: Bool) {
        let keep = draft {
            $0.hasTargets = true
            $0.targetKeep = pattern
        }
        #expect(keep.messages(at: "targets.keep").isEmpty == compiles)
    }

    @Test("a (?P=name) back reference reads as ICU's \\k<name>")
    func backReference() {
        #expect(
            draft {
                $0.hasTargets = true
                $0.targetValid = #"(?P<q>['"]).*(?P=q)"#
            }.isValid)
    }

    @Test("every field of the gate has a rule at its Python path")
    func rules() {
        let bad = draft {
            $0.timeout = 0
            $0.hasTargets = true
            $0.targetMap = [.init(from: "(", to: "x"), .init(from: "a", to: ""), .init(from: "b", to: "c")]
            $0.targetItems = [.init(from: "", to: "x")]
            $0.targetValid = "["
            $0.hasSetup = true
            $0.setupRun = " "
        }
        #expect(
            bad.problems.map(\.path) == [
                "timeout_s", "targets.map[0]", "targets.map[1]", "targets.valid", "targets.item", "setup.name",
                "setup.run",
            ])
        #expect(bad.messages(at: "targets.map").count == 2)
        #expect(bad.messages(at: "targets.map[1]").count == 1)
    }

    @Test("the timeout runs from 1 s to 24 h, and none is fine")
    func timeout() {
        #expect(draft { $0.timeout = nil }.isValid)
        #expect(draft { $0.timeout = 86400 }.isValid)
        #expect(!draft { $0.timeout = 86401 }.isValid)
    }

    @Test(
        "run starts as an argv for a plain word list, else through bash",
        arguments: [
            ("cljfmt fix {files}", "", "A plain word list: runs as an argv, with no shell."),
            ("cljfmt fix {files}", "cd ui", "Runs through bash -c."),
            ("npx karma --client.args {item}", "", "A plain word list: runs as an argv, with no shell."),
            ("make test | tee log", "", "Runs through bash -c."),
            ("echo 'it'\"'\"'s'", "", "A plain word list: runs as an argv, with no shell."),
            ("echo  twice", "", "Runs through bash -c."),
            ("echo \"open", "", "Unclosed quote or trailing backslash: the gate cannot start."),
            ("echo done\\", "", "Unclosed quote or trailing backslash: the gate cannot start."),
        ])
    func runCaption(run: String, prelude: String, caption: String) {
        #expect(
            draft {
                $0.run = run
                $0.prelude = prelude
            }.runCaption == caption)
    }

    @Test("hints say where {files} and {item} are empty or missing")
    func hints() {
        #expect(draft().hints.isEmpty)
        #expect(draft { $0.run = "cljfmt fix" }.hints == ["Add {files} so the formatter gets the changed paths."])
        #expect(
            draft {
                $0.kind = .test
                $0.run = "t {item}"
            }.hints.count == 1)
        #expect(
            draft {
                $0.kind = .test
                $0.run = "t {item}"
                $0.hasTargets = true
            }.hints.isEmpty)
        #expect(
            draft {
                $0.hasSetup = true
                $0.setupRun = "build {item}"
            }.hints.count == 1)
    }

    @Test("a gate lands at the end of its kind, so format stays ahead of test")
    func kindOrder() throws {
        var list = GateList(try JSONValue(encoding: try iprally().map { try $0.decoded(GateConfig.self) }))
        #expect(list.save(draft { $0.name = "eslint" }.gate, at: nil) == 1)
        #expect(
            list.save(
                draft {
                    $0.name = "unit"
                    $0.kind = .test
                }.gate, at: nil) == 3)
        #expect(list.configs.map(\.name) == ["cljfmt", "eslint", "Karma", "unit"])
        #expect(
            list.save(
                draft {
                    $0.name = "Karma"
                    $0.kind = .format
                }.gate, at: 2) == 2)
        #expect(list.configs.map(\.kind) == [.format, .format, .format, .test])
        #expect(
            list.save(
                draft {
                    $0.name = "unit 2"
                    $0.kind = .test
                }.gate, at: 3) == 3)
        #expect(list.configs.map(\.name) == ["cljfmt", "eslint", "Karma", "unit 2"])
    }

    @Test("the first test gate goes last, the first format gate goes first")
    func firstOfKind() {
        var list = GateList([])
        #expect(list.save(draft { $0.kind = .test }.gate, at: nil) == 0)
        #expect(list.save(draft().gate, at: nil) == 0)
        #expect(list.configs.map(\.kind) == [.format, .test])
    }

    @Test("a list holds at most ten gates")
    func limit() {
        var list = GateList([])
        for _ in 0..<GateDraft.maxGates { list.save(draft().gate, at: nil) }
        #expect(!list.canAdd)
    }

    @Test("the store writes the gate into the draft of its scope")
    @MainActor func store() async throws {
        let store = SettingsStore(daemon: ScriptedDaemon(config: [.success(try Settings.envelope())]))
        await store.load()
        let landing = store.saveGate(draft { $0.name = "eslint" }.gate, at: nil, in: Settings.gitops)
        #expect(landing == 0)
        #expect(store.gates(in: Settings.gitops).configs.map(\.name) == ["eslint"])
        #expect(store.gates(in: .allRepos).configs.isEmpty)
    }

    @Test("a 422 under fix.gates[i] names the gate and the field")
    func errors() throws {
        let problems = try JSONDecoder().decode(
            [APIErrorBody.Problem].self,
            from: Data(
                """
                [{"path": "fix.gates[1].run", "message": "must be a non-empty string"},
                 {"path": "projects[\\"iprally/gitops\\"].fix.gates[0].targets.keep", "message": "must be a valid regex"},
                 {"path": "fix.gates", "message": "must be an array of 0-10 items"},
                 {"path": "fix.test_retries", "message": "x"}]
                """.utf8))
        let errors = FieldErrors(problems)
        #expect(
            errors.gates(in: .allRepos).map { [$0.index.map(String.init) ?? "-", $0.field] } == [
                ["1", "run"], ["-", ""],
            ])
        #expect(errors.gates(in: Settings.gitops).map(\.field) == ["targets.keep"])
        #expect(errors.messages(within: "fix.gates[1].run", in: .allRepos) == ["must be a non-empty string"])
        #expect(errors.unclaimed(in: .allRepos, by: ["fix.gates"]).map(\.path) == ["fix.test_retries"])
    }
}
