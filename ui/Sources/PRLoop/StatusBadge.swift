import PRLoopKit
import SwiftUI

struct StatusBadge: View {
    let style: StatusStyle

    init(style: StatusStyle) {
        self.style = style
    }

    init(status: String) {
        style = StatusStyle(status)
    }

    var body: some View {
        Label {
            Text(style.label)
        } icon: {
            Image(systemName: style.symbol).foregroundStyle(style.tone.color)
        }
    }
}
