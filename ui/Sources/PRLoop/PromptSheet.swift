import PRLoopKit
import SwiftUI

struct PromptSheet: View {
    let name: String
    @Environment(SettingsStore.self) private var settings
    @Environment(\.dismiss) private var dismiss
    @State private var prompt: Prompt?
    @State private var failure: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(verbatim: name).font(.headline)
            if let prompt {
                ScrollView {
                    Text(verbatim: prompt.text).monospaced().textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading).padding(8)
                }
                .frame(height: 380)
                .background(.background, in: .rect(cornerRadius: 6))
                Text("Placeholders").font(.subheadline.weight(.semibold))
                Text(verbatim: prompt.placeholders.map { "{\($0)}" }.joined(separator: "  "))
                    .monospaced().textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                Text(
                    verbatim:
                        "Prompts change through git: \(prompt.path.split(separator: "/").suffix(3).joined(separator: "/"))"
                )
                .font(.caption).foregroundStyle(.secondary)
            } else if let failure {
                ContentUnavailableView(
                    "Cannot Load the Prompt", systemImage: "exclamationmark.triangle",
                    description: Text(verbatim: failure))
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
            HStack {
                Spacer()
                Button("Done") { dismiss() }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 640)
        .task(id: name) {
            do {
                prompt = try await settings.prompt(named: name)
            } catch {
                failure = ActionFailure(pr: nil, error: error).message
            }
        }
    }
}
