import AppKit
import PRWizardKit
import SwiftUI

struct ConventionsLine: View {
    let line: PRWizardKit.ConventionsLine
    let checkout: String?

    var body: some View {
        if let sentence = line.sentence {
            Text(verbatim: sentence).foregroundStyle(.secondary)
        }
        ForEach(line.rows, id: \.kind) { row in
            LabeledContent(row.title) {
                HStack(spacing: 6) {
                    ForEach(row.shown, id: \.self) { item(row.kind, $0) }
                    if !row.hidden.isEmpty { Text(verbatim: "+\(row.hidden.count)").foregroundStyle(.secondary) }
                    if row.kind == .files, let ref = line.ref {
                        Text(verbatim: "on \(ref)").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .help((row.shown + row.hidden).joined(separator: "\n"))
        }
    }

    @ViewBuilder private func item(_ kind: PRWizardKit.ConventionsLine.Row.Kind, _ name: String) -> some View {
        if kind == .files, let checkout {
            Button(name) {
                NSWorkspace.shared.activateFileViewerSelecting([URL(filePath: checkout).appending(path: name)])
            }
            .buttonStyle(.link)
        } else {
            Text(verbatim: name)
        }
    }
}
