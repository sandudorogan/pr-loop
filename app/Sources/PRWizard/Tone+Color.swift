import PRWizardKit
import SwiftUI

extension Tone {
    var color: Color {
        switch self {
        case .neutral: .secondary
        case .working: .accentColor
        case .good: .green
        case .info: .blue
        case .caution: .yellow
        case .attention: .orange
        case .bad: .red
        }
    }
}
