import Foundation

/// One fixer gate as the editor holds it: plain text and lists, so a half-typed field never has to be a valid gate.
///
/// `gate` builds the `GateConfig` the daemon takes. Blank text becomes an absent key, and keys the app does not
/// know ride through `base`.
public struct GateDraft: Hashable, Sendable {
    public struct Pair: Hashable, Sendable {
        public var from = ""
        public var to = ""

        public init(from: String = "", to: String = "") {
            self.from = from
            self.to = to
        }
    }

    public struct Problem: Hashable, Sendable {
        public let path: String
        public let message: String
    }

    public static let maxGates = 10

    public var name: String
    public var kind: GateKind
    public var when: [String]
    public var run: String
    public var cwd: String
    public var prelude: String
    public var requires: String
    public var needs: [String]
    public var timeout: Int?
    public var usesSlot: Bool
    public var protect: [String]
    public var note: String
    public var hasTargets: Bool
    public var targetMap: [Pair]
    public var targetKeep: String
    public var targetExists: Bool
    public var targetItems: [Pair]
    public var targetValid: String
    public var hasSetup: Bool
    public var setupName: String
    public var setupRun: String
    private let base: GateConfig

    public init(_ gate: GateConfig? = nil) {
        let gate = gate ?? GateConfig(name: "", kind: .format, when: [], run: "", unknown: [:])
        base = gate
        name = gate.name
        kind = gate.kind
        when = gate.when
        run = gate.run
        cwd = gate.cwd ?? ""
        prelude = gate.prelude ?? ""
        requires = gate.requires ?? ""
        needs = gate.needs ?? []
        timeout = gate.timeout
        usesSlot = gate.usesSlot ?? false
        protect = gate.protect ?? []
        note = gate.note ?? ""
        let targets = gate.targets
        hasTargets = targets != nil
        targetMap = (targets?.map ?? []).map { Pair(from: $0.first ?? "", to: $0.dropFirst().first ?? "") }
        targetKeep = targets?.keep ?? ""
        targetExists = targets?.exists ?? false
        targetItems = (targets?.item ?? [:]).sorted { $0.key < $1.key }.map { Pair(from: $0.key, to: $0.value) }
        targetValid = targets?.valid ?? ""
        hasSetup = gate.setup != nil
        setupName = gate.setup?.name ?? ""
        setupRun = gate.setup?.run ?? ""
    }

    public var gate: GateConfig {
        var out = base
        out.name = name.trimmed
        out.kind = kind
        out.when = Self.words(when)
        out.run = run
        out.cwd = Self.text(cwd)
        out.prelude = Self.text(prelude)
        out.requires = Self.text(requires)
        out.needs = Self.words(needs).nilIfEmpty
        out.timeout = timeout
        out.usesSlot = usesSlot ? true : base.usesSlot.map { _ in false }
        out.protect = Self.words(protect).nilIfEmpty
        out.note = Self.text(note)
        out.targets = hasTargets ? targets : nil
        out.setup = hasSetup ? setup : nil
        return out
    }

    private var targets: GateTargets {
        var out = base.targets ?? GateTargets(unknown: [:])
        out.map = targetMap.filter { !$0.isBlank }.map { [$0.from, $0.to] }.nilIfEmpty
        out.keep = Self.text(targetKeep)
        out.exists = targetExists ? true : out.exists.map { _ in false }
        out.item = Dictionary(targetItems.filter { !$0.isBlank }.map { ($0.from, $0.to) }) { $1 }.nilIfEmpty
        out.valid = Self.text(targetValid)
        return out
    }

    private var setup: GateSetup {
        var out = base.setup ?? GateSetup(name: "", run: "", unknown: [:])
        out.name = setupName.trimmed
        out.run = setupRun
        return out
    }

    private static func text(_ value: String) -> String? { value.trimmed.isEmpty ? nil : value.trimmed }
    private static func words(_ values: [String]) -> [String] { values.map(\.trimmed).filter { !$0.isEmpty } }
}

extension GateDraft.Pair {
    fileprivate var isBlank: Bool { from.isEmpty && to.isEmpty }
}

extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}

extension Collection {
    fileprivate var nilIfEmpty: Self? { isEmpty ? nil : self }
}
