import SwiftUI

struct FixerPane: View {
    var body: some View {
        ContentUnavailableView("Fixer", systemImage: "wrench.and.screwdriver").frame(width: 600, height: 240)
    }
}
