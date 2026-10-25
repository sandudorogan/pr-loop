import SwiftUI

struct FixerPane: View {
    var body: some View {
        ScopedPane(width: 600, keys: []) { _ in
            ContentUnavailableView("Fixer", systemImage: "wrench.and.screwdriver")
        }
    }
}
