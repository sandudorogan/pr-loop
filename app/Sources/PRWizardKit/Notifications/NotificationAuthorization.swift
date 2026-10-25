public enum NotificationAuthorization: Hashable, Sendable {
    /// `temporary`: allowed, but the alert style is not Persistent, so a banner goes away on its own.
    case notDetermined, denied, temporary, authorized

    public var allowsPosting: Bool { self == .authorized || self == .temporary }
}
