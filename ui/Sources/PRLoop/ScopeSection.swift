import PRLoopKit
import SwiftUI

/// The judge's verdict first, then what the PR does against what it claims, then what does not belong. The full
/// change list stays folded, and file paths live in tooltips.
struct ScopeSection: View {
    let scope: Scope

    var body: some View {
        Section {
            if let style = scope.style {
                VStack(alignment: .leading, spacing: 2) {
                    Label(style.label, systemImage: style.symbol).font(.headline).foregroundStyle(style.tone.color)
                    if let reason = scope.reason { Text(reason).foregroundStyle(.secondary) }
                }
            }
            if let note = scope.note {
                HStack(spacing: 6) {
                    if scope.status == .running { ProgressView().controlSize(.small) }
                    Text(note)
                }
                .font(.callout).foregroundStyle(.secondary).help(scope.error ?? "")
            }
            if let intent = scope.intent, let stated = scope.stated {
                VStack(alignment: .leading, spacing: 8) {
                    Claim(title: "What it does", text: intent)
                    Claim(title: "What it claims", text: stated)
                }
            }
            if !scope.outOfScope.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Out of scope").font(.caption).foregroundStyle(.secondary)
                    ForEach(scope.outOfScope, id: \.self) { OutOfScopeRow(change: $0) }
                }
            }
            if !scope.touches.isEmpty {
                Flow {
                    Text("Touches").font(.caption).foregroundStyle(.secondary)
                    ForEach(scope.touches, id: \.self) { touch in
                        Chip(tint: .secondary) { Text(touch.kind) }.help(touch.help)
                    }
                }
            }
            if !scope.changes.isEmpty {
                DisclosureGroup("All changes (\(scope.changes.count))") {
                    ForEach(scope.changes, id: \.self) { ChangeRow(change: $0) }
                }
            }
        } header: {
            SectionTitle(title: "Scope", symbol: "scope", tint: .teal)
        }
    }
}

private struct Claim: View {
    let title: LocalizedStringKey
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(text).fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct OutOfScopeRow: View {
    let change: ScopeChange

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Label {
                Text(change.what)
            } icon: {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Tone.attention.color)
            }
            Text(change.note).font(.caption).foregroundStyle(.secondary).padding(.leading, 22)
        }
        .fixedSize(horizontal: false, vertical: true)
        .help(change.help)
    }
}

private struct ChangeRow: View {
    let change: ScopeChange

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text(change.mark).monospaced()
                .foregroundStyle(change.isInScope ? Color.secondary : Tone.attention.color)
            Text(change.what).fixedSize(horizontal: false, vertical: true)
        }
        .help(change.help)
    }
}
