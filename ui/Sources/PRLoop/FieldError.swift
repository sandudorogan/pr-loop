import PRLoopKit
import SwiftUI

struct FieldError: View {
    let messages: [String]

    var body: some View {
        ForEach(messages, id: \.self) { message in
            Label {
                Text(verbatim: message)
            } icon: {
                Image(systemName: "xmark.circle.fill")
            }
            .font(.caption).foregroundStyle(Tone.bad.color)
        }
    }
}
