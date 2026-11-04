import PRLoopKit
import SwiftUI

struct RootsSheet: View {
    var body: some View {
        StringListSheet(title: "Find checkouts in", key: "detect.roots", scope: .allRepos, limit: 10)
    }
}
