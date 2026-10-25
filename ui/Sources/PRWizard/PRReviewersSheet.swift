import PRWizardKit
import SwiftUI

/// Every reviewer field for one PR, edited as a copy: Done writes the whole list in one change.
struct PRReviewersSheet: View {
    let initial: [ReviewerConfig]
    let choices: Choices
    let save: ([ReviewerConfig]) -> Void
    @Environment(PRSettingsStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var reviewers: [ReviewerConfig] = []
    @State private var selected = 0

    var body: some View {
        VStack(alignment: .leading) {
            Picker("Reviewer", selection: $selected) {
                ForEach(Array(reviewers.enumerated()), id: \.offset) { Text($1.label).tag($0) }
            }
            .fixedSize()
            if reviewers.indices.contains(selected) {
                ReviewerForm(
                    reviewer: $reviewers[selected], choices: choices,
                    errors: { store.messages(at: "review.reviewers[\(selected)].\($0)") })
            }
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Done") {
                    save(reviewers)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .disabled(reviewers == initial)
            }
        }
        .padding()
        .frame(width: 560)
        .onAppear { reviewers = initial }
    }
}
