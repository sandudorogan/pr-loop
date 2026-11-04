import PRLoopKit
import SwiftUI

struct StatusBadge: View {
    let status: String

    var body: some View {
        let style = StatusStyle(status)
        Label {
            Text(style.label)
        } icon: {
            Image(systemName: style.symbol).foregroundStyle(style.tone.color)
        }
    }
}
