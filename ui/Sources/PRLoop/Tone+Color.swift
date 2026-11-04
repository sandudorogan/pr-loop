import PRLoopKit
import SwiftUI

extension Tone {
    var color: Color {
        switch self {
        case .neutral: .secondary
        case .working: .accentColor
        case .good: .green
        case .mine: .purple
        case .info: .blue
        case .caution: .yellow
        case .attention: .orange
        case .bad: .red
        }
    }
}
