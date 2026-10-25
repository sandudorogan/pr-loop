import PRWizardKit
import SwiftUI

struct DurationField: View {
    let title: String
    @Binding var seconds: Int
    var bareUnit = DurationFormat.Unit.minutes

    var body: some View {
        TextField(title, value: $seconds, format: DurationFormat(bareUnit: bareUnit))
            .multilineTextAlignment(.trailing)
            .help("Like 45 min, 4 h or 1 h 30 min")
    }
}
