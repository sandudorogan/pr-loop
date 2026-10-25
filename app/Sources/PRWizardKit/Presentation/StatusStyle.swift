import Foundation

public struct StatusStyle: Hashable, Sendable {
    public let symbol: String
    public let tone: Tone
    public let label: String

    public init(_ status: String) {
        (symbol, tone, label) =
            switch status {
            case "reviewing": ("eye", .working, "Reviewing")
            case "fixing": ("hammer", .working, "Fixing")
            case "queued": ("clock", .neutral, "Queued")
            case "ready": ("checkmark.seal.fill", .good, "Ready")
            case "clean": ("checkmark.seal.fill", .good, "Clean")
            case "quality-only": ("checkmark.seal.fill", .good, "Notes only")
            case "posted": ("text.bubble", .info, "Findings posted")
            case "held": ("pause.circle", .neutral, "Held")
            case "needs-human": ("person.fill.questionmark", .attention, "Needs you")
            case "too-big": ("person.fill.questionmark", .attention, "Too big")
            case "failed": ("xmark.octagon", .bad, "Failed")
            case "limited": ("hourglass", .attention, "Usage limit")
            case "skipped", "unchanged", "trivial", "baseline", "new": ("minus.circle", .neutral, status.capitalized)
            case "pushed": ("arrow.up.circle", .info, "Pushed")
            case "tests-red": ("xmark.octagon", .bad, "Tests red")
            case "error": ("xmark.octagon", .bad, "Error")
            case "ci-stuck": ("exclamationmark.triangle", .attention, "CI stuck")
            case "nothing-to-fix": ("checkmark.circle", .good, "Nothing to fix")
            case "refuted-only": ("checkmark.circle", .good, "Refuted only")
            case "no-changes": ("checkmark.circle", .good, "No changes")
            default: ("questionmark.circle", .neutral, status)
            }
    }
}
