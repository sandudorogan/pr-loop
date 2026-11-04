import PRLoopKit

extension PRMarkers.Source {
    var kind: OverrideMarker.Kind {
        switch self {
        case .default: .inherited
        case .project(let repo): .inheritedFrom(repo)
        case .pr: .overridden
        case .label(let label): .label(label)
        }
    }

    var isLabel: Bool {
        if case .label = self { true } else { false }
    }

    var caption: String {
        switch self {
        case .default: "Default"
        case .project(let repo): "Inherited from \(repo)"
        case .pr: "Overridden"
        case .label(let label): "Label \(label) on GitHub"
        }
    }
}
