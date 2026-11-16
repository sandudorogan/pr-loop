import PRLoopKit
import SwiftUI

/// The last review and fix pass, one row each. The table's Status and Detail already say where the PR stands, so this
/// sits at the bottom, and each pass's note is its tooltip.
struct PassesSection: View {
    let model: InspectorModel

    var body: some View {
        let item = model.item
        Section {
            if let review = item.review, let status = model.reviewStatus, let line = model.reviewLine {
                PassRow(title: "Review", status: status, line: line, at: review.at, note: review.note)
            }
            if let fix = item.fix, let line = model.fixLine {
                PassRow(title: "Fix", status: fix.status, line: line, at: fix.at, note: fix.note)
            }
        } header: {
            SectionTitle(title: "Last passes", symbol: "clock.arrow.circlepath", tint: .secondary)
        }
    }
}

private struct PassRow: View {
    let title: LocalizedStringKey
    let status: String
    let line: String
    let at: Date
    let note: String

    var body: some View {
        LabeledContent(title) {
            VStack(alignment: .trailing, spacing: 2) {
                StatusBadge(status: status)
                Text("\(line) · \(at, format: .relative(presentation: .named))")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .help(note)
    }
}
