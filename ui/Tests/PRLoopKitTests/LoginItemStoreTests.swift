import Foundation
import PRLoopKit
import ServiceManagement
import Testing

@MainActor @Suite struct LoginItemStoreTests {
    private struct Refused: LocalizedError {
        var errorDescription: String? { "Operation not permitted" }
    }

    private final class FakeService: LoginItemService {
        var status: SMAppService.Status
        let registers: SMAppService.Status
        let failure: (any Error)?

        init(_ status: SMAppService.Status, registers: SMAppService.Status = .enabled, failure: (any Error)? = nil) {
            self.status = status
            self.registers = registers
            self.failure = failure
        }

        func register() throws {
            if let failure { throw failure }
            status = registers
        }

        func unregister() throws {
            if let failure { throw failure }
            status = .notRegistered
        }
    }

    @Test(
        "each status maps to the toggle and its caption",
        arguments: [
            (.notRegistered, false, false, nil),
            (.enabled, true, false, nil),
            (.requiresApproval, true, true, "Needs approval in System Settings › Login Items."),
            (.notFound, false, false, nil),
        ] as [(SMAppService.Status, Bool, Bool, String?)])
    func mapping(status: SMAppService.Status, isOn: Bool, needsApproval: Bool, caption: String?) {
        let state = LoginItemState(status)
        #expect(state.isOn == isOn)
        #expect(state.needsApproval == needsApproval)
        #expect(state.caption == caption)
    }

    @Test("turning it on registers and reads the new status back")
    func on() {
        let store = LoginItemStore(service: FakeService(.notRegistered, registers: .requiresApproval))
        store.setOn(true)
        #expect(store.state == LoginItemState(.requiresApproval))
        #expect(store.caption == "Needs approval in System Settings › Login Items.")
    }

    @Test("turning it off unregisters")
    func off() {
        let store = LoginItemStore(service: FakeService(.enabled))
        store.setOn(false)
        #expect(store.state.isOn == false)
        #expect(store.caption == nil)
    }

    @Test("a refused change keeps the status and shows the error")
    func refused() {
        let service = FakeService(.notRegistered, failure: Refused())
        let store = LoginItemStore(service: service)
        store.setOn(true)
        #expect(store.state.isOn == false)
        #expect(store.caption == "Operation not permitted")
    }

    @Test("refresh picks up a status changed in System Settings")
    func refresh() {
        let service = FakeService(.requiresApproval)
        let store = LoginItemStore(service: service)
        service.status = .enabled
        store.refresh()
        #expect(store.state == LoginItemState(.enabled))
    }
}
