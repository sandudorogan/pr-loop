import SwiftUI

struct ReviewersPane: View {
    var body: some View {
        ScopedPane(width: 720, keys: []) { _ in
            ContentUnavailableView("Reviewers", systemImage: "person.3")
        }
    }
}
