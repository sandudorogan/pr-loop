import PRWizardKit
import SwiftUI

struct FindingsView: View {
    let findings: Findings

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(findings.header).font(.subheadline.weight(.semibold))
            if let note = findings.staleNote {
                Label(note, systemImage: "clock.arrow.circlepath").foregroundStyle(Tone.attention.color)
                if let at = findings.reviewedAt {
                    Text("Last reviewed \(at, format: .relative(presentation: .named))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            ForEach(findings.reviewers) { ReviewerRow(reviewer: $0) }
            if !findings.top.isEmpty {
                Divider()
                ForEach(findings.top, id: \.self) { TopFindingRow(finding: $0) }
            }
        }
    }
}

private struct ReviewerRow: View {
    let reviewer: ReviewerFindings

    var body: some View {
        OptionalLink(url: reviewer.url) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(reviewer.label).lineLimit(1)
                    Text(verbatim: "\(reviewer.result.label) · \(reviewer.atFloor) at floor")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                ForEach(reviewer.counts.nonZero, id: \.severity) {
                    SeverityCapsule(severity: $0.severity, count: $0.count)
                }
            }
        }
        .help("Ran on \(reviewer.engine)")
    }
}

private struct TopFindingRow: View {
    let finding: TopFinding

    var body: some View {
        OptionalLink(url: finding.url) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline) {
                    SeverityCapsule(severity: finding.severity)
                    Text(finding.title).lineLimit(1).truncationMode(.tail)
                }
                Text([finding.location, finding.reviewer].compactMap(\.self).joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            }
        }
    }
}

private struct SeverityCapsule: View {
    let severity: Severity
    var count: Int?

    var body: some View {
        let style = SeverityStyle(severity)
        Label {
            Text(count.map { "\($0) \(style.label)" } ?? style.label)
        } icon: {
            Image(systemName: style.symbol).foregroundStyle(style.tone.color)
        }
        .font(.caption)
        .padding(.horizontal, 6)
        .padding(.vertical, 1)
        .background(.quaternary, in: .capsule)
    }
}

private struct OptionalLink<Content: View>: View {
    let url: URL?
    @ViewBuilder let content: Content
    @Environment(\.openURL) private var openURL

    var body: some View {
        if let url {
            Button {
                openURL(url)
            } label: {
                content.contentShape(.rect)
            }
            .buttonStyle(.plain)
        } else {
            content
        }
    }
}
