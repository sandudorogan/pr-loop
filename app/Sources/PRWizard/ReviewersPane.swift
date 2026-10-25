import SwiftUI

struct ReviewersPane: View {
    var body: some View {
        ContentUnavailableView("Reviewers", systemImage: "person.3").frame(width: 720, height: 240)
    }
}
