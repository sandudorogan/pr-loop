import Foundation
import Observation

@MainActor @Observable public final class LoginItemStore {
    public private(set) var state: LoginItemState
    public private(set) var failure: String?

    private let service: any LoginItemService

    public init(service: any LoginItemService) {
        self.service = service
        state = LoginItemState(service.status)
    }

    public var caption: String? { failure ?? state.caption }

    public func setOn(_ isOn: Bool) {
        do {
            try isOn ? service.register() : service.unregister()
            failure = nil
        } catch {
            failure = error.localizedDescription
        }
        refresh()
    }

    public func refresh() {
        state = LoginItemState(service.status)
    }
}
