import SwiftUI

struct ModelField: View {
    let title: String
    @Binding var model: String?
    let defaultLabel: String
    let suggestions: [String]

    var body: some View {
        LabeledContent(title) {
            HStack(spacing: 4) {
                TextField(
                    title,
                    text: Binding {
                        model ?? ""
                    } set: {
                        model = $0.isEmpty ? nil : $0
                    },
                    prompt: Text(verbatim: defaultLabel)
                )
                .labelsHidden()
                .frame(width: 220)
                Menu {
                    Button(defaultLabel) { model = nil }
                    Divider()
                    ForEach(suggestions, id: \.self) { suggestion in
                        Button(suggestion) { model = suggestion }
                    }
                } label: {
                    Label("Suggestions", systemImage: "chevron.down")
                }
                .menuIndicator(.hidden)
                .labelStyle(.iconOnly)
                .fixedSize()
                .help("Suggestions. Any model name works.")
            }
        }
    }
}
