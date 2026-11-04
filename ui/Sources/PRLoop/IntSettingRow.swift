import PRLoopKit
import SwiftUI

struct IntSettingRow: View {
    enum Style {
        case stepper(ClosedRange<Int>)
        case field(unit: String)
    }

    let title: String
    let key: String
    let scope: SettingsScope
    let style: Style
    var per = 1
    @Environment(SettingsStore.self) private var settings

    var body: some View {
        let value = settings.int(key, in: scope, per: per)
        SettingRow(key: key, scope: scope) {
            LabeledContent(title) {
                switch style {
                case .stepper(let range):
                    HStack {
                        Text(verbatim: "\(value)").monospacedDigit()
                        Stepper(title, value: settings.intBinding(key, in: scope, per: per), in: range).labelsHidden()
                    }
                case .field(let unit):
                    HStack {
                        TextField(
                            title, value: settings.intBinding(key, in: scope, per: per),
                            format: .number.grouping(.never)
                        )
                        .labelsHidden().multilineTextAlignment(.trailing).frame(width: 72)
                        Text(verbatim: unit).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}
