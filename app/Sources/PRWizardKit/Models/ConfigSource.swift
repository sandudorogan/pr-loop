public enum ConfigSource: OpenEnum {
    case defaults, file
    case unknown(String)

    public static let known: [Self] = [.defaults, .file]

    public var rawValue: String {
        switch self {
        case .defaults: "defaults"
        case .file: "file"
        case .unknown(let value): value
        }
    }
}
