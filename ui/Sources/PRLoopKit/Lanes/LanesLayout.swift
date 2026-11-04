/// Which rows the Lanes pane shows for a scope, whether lanes are separate, and the project's status.
public struct LanesLayout: Hashable, Sendable {
    public enum Workers: Hashable, Sendable {
        case stepper
        case laneOff
        case sharedPool
        case unavailable
    }

    public let isGlobal: Bool
    public let showsTotals: Bool
    public let reviewTitle: String
    public let fixTitle: String
    public let review: Workers
    public let fix: Workers
    public let sharedNote: String?

    public init(scope: SettingsScope, isSeparate: Bool, project: Project?, isReviewOn: Bool, isFixOn: Bool) {
        func workers(isOn: Bool) -> Workers {
            guard project?.isAvailable == true else { return .unavailable }
            return !isOn ? .laneOff : isSeparate ? .stepper : .sharedPool
        }
        isGlobal = scope == .allRepos
        showsTotals = isGlobal && isSeparate
        if isGlobal {
            reviewTitle = isSeparate ? "Reviews per repo" : "Parallel reviews"
            fixTitle = isSeparate ? "Fix passes per repo" : "Parallel fix passes"
            (review, fix) = (.stepper, .stepper)
        } else {
            (reviewTitle, fixTitle) = ("Reviews", "Fix passes")
            (review, fix) = (workers(isOn: isReviewOn), workers(isOn: isFixOn))
        }
        sharedNote =
            switch (review == .sharedPool, fix == .sharedPool) {
            case (true, true): "Shares the review and fix pools with every repo."
            case (true, false): "Shares the review pool with every repo."
            case (false, true): "Shares the fix pool with every repo."
            case (false, false): nil
            }
    }
}
