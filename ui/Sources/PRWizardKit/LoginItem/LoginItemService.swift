import ServiceManagement

public protocol LoginItemService {
    var status: SMAppService.Status { get }
    func register() throws
    func unregister() throws
}
