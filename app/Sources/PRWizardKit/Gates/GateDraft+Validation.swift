import Foundation

extension GateDraft {
    /// The rules of `pr_wizard.config` `GATE`, at the paths its 422 details use inside one gate.
    public var problems: [Problem] {
        let gate = gate
        var out = [Problem]()
        func expect(_ path: String, _ ok: Bool, _ message: String) {
            if !ok { out.append(Problem(path: path, message: message)) }
        }
        let text = "must be a non-empty string"
        let regex = "must be a valid regex"
        expect("name", !gate.name.isEmpty, text)
        expect("when", !gate.when.isEmpty, "needs at least one glob")
        expect("run", !run.trimmed.isEmpty, text)
        expect("timeout_s", gate.timeout.map { (1...86400).contains($0) } ?? true, "must be 1 s to 24 h")
        if let targets = gate.targets {
            for (i, pair) in (targets.map ?? []).enumerated() {
                let ok = pair.count == 2 && !pair[0].isEmpty && !pair[1].isEmpty && PythonRegex.compiles(pair[0])
                expect("targets.map[\(i)]", ok, "needs a regex that compiles and a replacement")
            }
            expect("targets.keep", targets.keep.map(PythonRegex.compiles) ?? true, regex)
            expect("targets.valid", targets.valid.map(PythonRegex.compiles) ?? true, regex)
            expect("targets.item", !(targets.item ?? [:]).keys.contains(""), "needs a character to replace")
        }
        if let setup = gate.setup {
            expect("setup.name", !setup.name.isEmpty, text)
            expect("setup.run", !setup.run.trimmed.isEmpty, text)
        }
        return out
    }

    /// The messages at `path` or at an element below it (`when[0]` under `when`).
    public func messages(at path: String) -> [String] {
        problems.filter { $0.path == path || $0.path.hasPrefix("\(path)[") }.map(\.message)
    }

    public var isValid: Bool { problems.isEmpty }
}

extension GateDraft {
    public static let placeholders = "{files} is the changed paths that match When, shell-quoted. {item} is one target."

    /// How the daemon starts `run`: `pr_wizard.gates.argv` execs a plain word list and gives the rest to bash.
    public var runCaption: String {
        let line = Self.filled(prelude.isEmpty ? run : "\(prelude) && \(run)")
        return switch ShellWords.split(line) {
        case nil: "Unclosed quote or trailing backslash: the gate cannot start."
        case _ where ShellWords.isPlain(line): "A plain word list: runs as an argv, with no shell."
        default: "Runs through bash -c."
        }
    }

    public var hints: [String] {
        [
            kind == .format && !run.contains("{files}") ? "Add {files} so the formatter gets the changed paths." : nil,
            run.contains("{item}") && (kind == .format || !hasTargets)
                ? "{item} is empty here: only a test gate with targets sets it." : nil,
            hasSetup && setupRun.contains("{item}") ? "Setup runs once, before any item: {item} is empty there." : nil,
        ].compactMap { $0 }
    }

    private static func filled(_ command: String) -> String {
        command.replacingOccurrences(of: "{files}", with: "x").replacingOccurrences(of: "{item}", with: "x")
    }
}
