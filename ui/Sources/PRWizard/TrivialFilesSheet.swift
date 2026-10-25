import PRWizardKit
import SwiftUI

struct TrivialFilesSheet: View {
    let scope: SettingsScope

    var body: some View {
        StringListSheet(title: "Trivial files", key: "review.trivial", scope: scope, limit: 50)
    }
}
