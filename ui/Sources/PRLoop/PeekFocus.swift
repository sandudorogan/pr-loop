import PRLoopKit
import SwiftUI

struct PeekFocus {
    let model: PeekModel
    let id: String?

    func toggle() {
        if let id { model.toggle(id) }
    }

    func pressSpace() -> KeyPress.Result { model.toggleOnSpace(id) ? .handled : .ignored }
}
