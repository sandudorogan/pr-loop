import Foundation

public struct ActionFailure: Identifiable, Sendable {
    public let id = UUID()
    public let pr: PRRef?
    public let error: any Error

    public init(pr: PRRef?, error: any Error) {
        self.pr = pr
        self.error = error
    }

    public var message: String {
        let subject = pr.map { "\(ProjectSummary.shortName(of: $0.repo))#\($0.number)" } ?? "The PR"
        return switch error {
        case APIError.http(_, "busy", _, _): "\(subject) is in a live run"
        case APIError.http(_, _, let message, _): message
        case APIError.down: "PR Wizard is not running"
        default: error.localizedDescription
        }
    }
}
