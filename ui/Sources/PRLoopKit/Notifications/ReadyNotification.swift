import Foundation

public struct ReadyNotification: Hashable, Sendable {
    public let id: String
    public let key: String
    public let title = "Ready for your approval"
    public let subtitle: String
    public let body: String
    public let url: URL

    public init(_ event: DaemonEvent) {
        id = event.id
        key = event.key
        body = event.title
        url = event.url
        let project = event.repo.split(separator: "/").last.map(String.init) ?? event.repo
        let verdict: String? =
            switch event.verdict {
            case .clean: "clean"
            case .qualityOnly: "notes only"
            default: nil
            }
        let author = event.authorName ?? event.author
        subtitle = ["\(project) #\(event.number)", author, verdict].compactMap(\.self).joined(separator: " · ")
    }
}
