import Foundation
import PRWizardKit
import Testing

@Suite struct SeverityStyleTests {
    @Test(
        "maps every severity to a symbol, a tone and its word",
        arguments: [
            (Severity.critical, "exclamationmark.octagon.fill", Tone.bad, "critical"),
            (.high, "exclamationmark.triangle.fill", .attention, "high"),
            (.medium, "exclamationmark.circle.fill", .caution, "medium"),
            (.low, "info.circle", .neutral, "low"),
            (.unknown("blocker"), "questionmark.circle", .neutral, "blocker"),
        ])
    func style(severity: Severity, symbol: String, tone: Tone, label: String) {
        let style = SeverityStyle(severity)
        #expect((style.symbol, style.tone, style.label) == (symbol, tone, label))
    }

    @Test("lists only the severities that have findings, worst first")
    func nonZero() throws {
        let json = #"{"critical": 1, "high": 0, "medium": 2, "low": 3}"#
        let counts = try JSONDecoder().decode(SeverityCounts.self, from: Data(json.utf8))
        #expect(counts.nonZero.map { "\($0.count) \($0.severity.rawValue)" } == ["1 critical", "2 medium", "3 low"])
    }
}
