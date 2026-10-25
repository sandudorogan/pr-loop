import SwiftUI

/// A menu of known values plus the inherited default (`nil`). A value outside the list still shows.
struct OptionPicker: View {
    let title: String
    let selection: String?
    let options: [String]
    let defaultLabel: String
    let choose: (String?) -> Void

    var body: some View {
        Picker(
            title,
            selection: Binding {
                selection
            } set: {
                choose($0)
            }
        ) {
            Text(verbatim: defaultLabel).tag(String?.none)
            Divider()
            ForEach(options + [selection].compactMap { $0 }.filter { !options.contains($0) }, id: \.self) {
                Text(verbatim: $0).tag(Optional($0))
            }
        }
    }
}
