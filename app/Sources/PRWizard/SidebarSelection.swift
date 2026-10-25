enum SidebarSelection: Hashable, RawRepresentable {
    case all
    case repo(String)

    init(rawValue: String) {
        self = rawValue.isEmpty ? .all : .repo(rawValue)
    }

    var rawValue: String { repo ?? "" }

    var repo: String? {
        guard case .repo(let repo) = self else { return nil }
        return repo
    }
}
