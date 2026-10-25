import SwiftUI

struct LanesPane: View {
    var body: some View {
        ContentUnavailableView("Lanes", systemImage: "arrow.triangle.branch").frame(width: 600, height: 240)
    }
}
