import PRWizardKit
import SwiftUI

struct OverrideMarker: View {
    enum Kind: Hashable {
        case inherited
        case inheritedFrom(String)
        case overridden
        case label(String)
    }

    let kind: Kind
    var useDefault: () -> Void = {}

    var body: some View {
        switch kind {
        case .inherited:
            Text("Default").font(.caption).foregroundStyle(.secondary)
        case .inheritedFrom(let repo):
            Text(verbatim: "Inherited from \(repo)").font(.caption).foregroundStyle(.secondary)
        case .label(let label):
            Label {
                Text(verbatim: "Label \(label) on GitHub")
            } icon: {
                Image(systemName: "tag")
            }
            .font(.caption).foregroundStyle(.secondary)
        case .overridden:
            HStack(spacing: 4) {
                Text("Overridden").font(.caption).padding(.horizontal, 6).padding(.vertical, 1)
                    .background(.quaternary, in: .capsule)
                Button("Use Default", systemImage: "arrow.uturn.backward", action: useDefault)
                    .labelStyle(.iconOnly).buttonStyle(.borderless).help("Use Default")
            }
        }
    }
}

extension OverrideMarker {
    init(_ key: String, in scope: SettingsScope, store: SettingsStore) {
        self.init(kind: store.draft.isOverridden(key, in: scope) ? .overridden : .inherited) {
            store.useDefault(key, in: scope)
        }
    }
}
