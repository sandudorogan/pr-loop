import PRWizardKit
import SwiftUI

struct GateEditorSheet: View {
    let gate: GateConfig?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(verbatim: gate?.name ?? "New Gate").font(.headline)
            if let gate {
                Text(verbatim: gate.run).monospaced().textSelection(.enabled)
            }
            Text("The gate editor is not built yet. Until then, edit gates in the config file.")
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Done") { dismiss() }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 440)
    }
}
