extension SettingsStore {
    public func gates(in scope: SettingsScope) -> GateList {
        GateList(resolve("fix.gates", in: scope).value)
    }

    /// Writes one edited gate into the draft and returns where it landed.
    @discardableResult public func saveGate(_ gate: GateConfig, at index: Int?, in scope: SettingsScope) -> Int {
        var list = gates(in: scope)
        let landing = list.save(gate, at: index)
        set("fix.gates", to: list.value, in: scope)
        return landing
    }
}
