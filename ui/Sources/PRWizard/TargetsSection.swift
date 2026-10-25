import PRWizardKit
import SwiftUI

/// The `targets` of a test gate: one run per item, found by rewriting each changed path.
struct TargetsSection: View {
    @Binding var draft: GateDraft
    let errors: (String) -> [String]

    var body: some View {
        DisclosureGroup(isExpanded: $draft.hasTargets) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Without targets the gate runs once with {files}. With them it runs once per item.")
                    .font(.caption).foregroundStyle(.secondary)
                PairsEditor(
                    title: "Map", pairs: $draft.targetMap, from: "^ui/src/(.+)\\.cljs$", to: "ui/test/\\1_test.cljs",
                    caption: "Rewrites each changed path in turn: a regex and its replacement.")
                FieldError(messages: errors("targets.map"))
                field("Keep", $draft.targetKeep, "A target must match this regex. Group 1 is the item.", "targets.keep")
                Toggle("The target file must exist", isOn: $draft.targetExists)
                PairsEditor(
                    title: "Item", pairs: $draft.targetItems, from: "/", to: ".",
                    caption: "Swaps characters in the item, top to bottom: each pair sees the result of the one above.")
                FieldError(messages: errors("targets.item"))
                field("Valid", $draft.targetValid, "An item must match this regex, or it is skipped.", "targets.valid")
            }
            .padding(.top, 6)
        } label: {
            Text("Targets")
        }
    }

    private func field(_ title: String, _ text: Binding<String>, _ caption: String, _ path: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            TextField(title, text: text).monospaced()
            Text(verbatim: caption).font(.caption).foregroundStyle(.secondary)
            FieldError(messages: errors(path))
        }
    }
}

private struct PairsEditor: View {
    let title: String
    @Binding var pairs: [GateDraft.Pair]
    let from: String
    let to: String
    let caption: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(verbatim: title).font(.subheadline.weight(.semibold))
            ForEach(pairs.indices, id: \.self) { index in
                HStack {
                    TextField(title, text: $pairs[index].from, prompt: Text(verbatim: from)).labelsHidden()
                    Image(systemName: "arrow.right").foregroundStyle(.secondary).accessibilityHidden(true)
                    TextField(title, text: $pairs[index].to, prompt: Text(verbatim: to)).labelsHidden()
                    Button("Remove", systemImage: "minus.circle") { pairs.remove(at: index) }
                        .labelStyle(.iconOnly).buttonStyle(.borderless)
                }
                .monospaced()
            }
            HStack {
                Button("Add", systemImage: "plus") { pairs.append(GateDraft.Pair()) }
                    .labelStyle(.iconOnly).buttonStyle(.borderless)
                Text(verbatim: caption).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}
