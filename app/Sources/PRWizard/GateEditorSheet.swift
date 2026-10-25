import PRWizardKit
import SwiftUI

/// Edits one fixer gate. Done puts it into the draft of the pane, and Apply on the pane writes it.
struct GateEditorSheet: View {
    let scope: SettingsScope
    let index: Int?
    let onSave: (Int) -> Void
    @Environment(SettingsStore.self) private var settings
    @Environment(\.dismiss) private var dismiss
    @State private var draft: GateDraft
    @State private var isEdited = false

    init(scope: SettingsScope, index: Int?, gate: GateConfig?, onSave: @escaping (Int) -> Void) {
        self.scope = scope
        self.index = index
        self.onSave = onSave
        _draft = State(initialValue: GateDraft(gate))
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                Form {
                    row("Name", "name") { TextField("Name", text: $draft.name).labelsHidden() }
                    row("Kind", nil, caption: kindCaption) {
                        Picker("Kind", selection: $draft.kind) {
                            ForEach(GateKind.known, id: \.self) { Text(verbatim: $0.rawValue.capitalized).tag($0) }
                        }
                        .pickerStyle(.segmented).labelsHidden().fixedSize()
                    }
                    row("When", "when", caption: "Changed paths that start the gate. * also matches /.") {
                        GlobTokenField(title: "When", prompt: "*.clj *.cljs", tokens: $draft.when)
                    }
                    row("Run", "run", caption: draft.runCaption) {
                        TextEditor(text: $draft.run).monospaced().frame(height: 64)
                            .overlay(RoundedRectangle(cornerRadius: 4).stroke(.separator))
                    }
                    ForEach(draft.hints, id: \.self) {
                        Text(verbatim: $0).font(.caption).foregroundStyle(Tone.attention.color)
                    }
                    Text(verbatim: GateDraft.placeholders).font(.caption).foregroundStyle(.secondary)
                    mono("Working directory", "cwd", $draft.cwd, "Relative to the worktree. Default: its root.")
                    mono("Prelude", "prelude", $draft.prelude, "Runs first, as `prelude && run`.")
                    mono(
                        "Requires", "requires", $draft.requires,
                        "A program that must be on PATH, else the gate is skipped.")
                    if draft.kind == .test { testFields }
                    row("Note", "note", caption: "The sentence this gate adds to {GATES} in the fix prompt.") {
                        TextField("Note", text: $draft.note, axis: .vertical).lineLimit(1...4).labelsHidden()
                    }
                }
                .formStyle(.columns)
                .padding(20)
            }
            Divider()
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Done", action: save).keyboardShortcut(.defaultAction).disabled(!draft.isValid)
            }
            .padding()
        }
        .frame(width: 620, height: 640)
        .onChange(of: draft) { isEdited = true }
    }

    @ViewBuilder private var testFields: some View {
        row("Needs", "needs", caption: "Paths that must exist, else every item reads \"CI grades it\".") {
            GlobTokenField(title: "Needs", prompt: "ui/node_modules", tokens: $draft.needs)
        }
        TargetsSection(draft: $draft, errors: errors)
        DisclosureGroup(isExpanded: $draft.hasSetup) {
            VStack(alignment: .leading, spacing: 6) {
                TextField("Setup name", text: $draft.setupName)
                FieldError(messages: errors("setup.name"))
                TextField("Setup command", text: $draft.setupRun, axis: .vertical).monospaced().lineLimit(1...4)
                FieldError(messages: errors("setup.run"))
                Text("Runs once before the items. A failure is one red entry with this name.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding(.top, 6)
        } label: {
            Text("Setup")
        }
        row("Timeout", "timeout_s", caption: "Per command. A timeout is red. Empty: no limit.") {
            TextField("Timeout", value: $draft.timeout, format: DurationFormat(), prompt: Text("none"))
                .multilineTextAlignment(.trailing).frame(width: 110).labelsHidden()
        }
        row("Slot", nil, caption: "Cold JVM builds and browsers share 2 slots on this machine.") {
            Toggle("Uses a machine slot", isOn: $draft.usesSlot)
        }
        row("Protect", "protect", caption: "Files Codex must not edit to make a red gate pass.") {
            GlobTokenField(title: "Protect", prompt: "karma.conf.js package.json", tokens: $draft.protect)
        }
    }

    private var kindCaption: String {
        draft.kind == .format
            ? "Format gates run first, fix the files in place and never go red."
            : "Test gates run after the format gates. A red one goes back to Codex."
    }

    private func errors(_ path: String) -> [String] {
        var seen = Set<String>()
        let local = isEdited || index != nil ? draft.messages(at: path) : []
        let remote = index.map { settings.errors.messages(within: "fix.gates[\($0)].\(path)", in: scope) } ?? []
        return (local + remote).filter { seen.insert($0).inserted }
    }

    private func save() {
        onSave(settings.saveGate(draft.gate, at: index, in: scope))
        dismiss()
    }

    private func mono(_ title: String, _ path: String, _ text: Binding<String>, _ caption: String) -> some View {
        row(title, path, caption: caption) { TextField(title, text: text).monospaced().labelsHidden() }
    }

    private func row(
        _ title: String, _ path: String?, caption: String? = nil, @ViewBuilder control: () -> some View
    ) -> some View {
        LabeledContent(title) {
            VStack(alignment: .leading, spacing: 2) {
                control()
                if let caption { Text(verbatim: caption).font(.caption).foregroundStyle(.secondary) }
                if let path { FieldError(messages: errors(path)) }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
