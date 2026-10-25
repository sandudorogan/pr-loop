import ServiceManagement

public struct LoginItemState: Hashable, Sendable {
    public let isOn: Bool
    public let needsApproval: Bool
    public let caption: String?

    public init(_ status: SMAppService.Status) {
        switch status {
        case .enabled: (isOn, needsApproval, caption) = (true, false, nil)
        case .requiresApproval:
            (isOn, needsApproval, caption) = (true, true, "Needs approval in System Settings › Login Items.")
        default: (isOn, needsApproval, caption) = (false, false, nil)
        }
    }
}
