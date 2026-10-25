import PRWizardKit

struct PeekFocus {
    let model: PeekModel
    let id: String?

    func toggle() {
        if let id { model.toggle(id) }
    }
}
