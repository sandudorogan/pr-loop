import PRWizardKit
import Testing

@Suite struct DurationFormatTests {
    @Test(
        "formats seconds in the largest units",
        arguments: [
            (2700, "45 min"), (14400, "4 h"), (5400, "1 h 30 min"), (90, "1 min 30 s"), (3601, "1 h 1 s"), (0, "0 s"),
        ])
    func format(seconds: Int, text: String) {
        #expect(DurationFormat().format(seconds) == text)
    }

    @Test(
        "parses units, spaces and case",
        arguments: [
            ("45 min", 2700), ("4h", 14400), ("1 h 30 min", 5400), (" 2 Hours ", 7200), ("90 s", 90), ("1h30m", 5400),
            ("45", 2700),
        ])
    func parse(text: String, seconds: Int) throws {
        #expect(try DurationFormat().parseStrategy.parse(text) == seconds)
    }

    @Test("a bare number reads in the field's unit")
    func bare() throws {
        #expect(try DurationFormat(bareUnit: .hours).parseStrategy.parse("4") == 14400)
    }

    @Test("rejects what is not a duration", arguments: ["", "abc", "4 days", "4 h x", "-4 min", "min"])
    func invalid(text: String) {
        #expect(throws: (any Error).self) { try DurationFormat().parseStrategy.parse(text) }
    }

    @Test("a formatted value parses back", arguments: [60, 2700, 5400, 14400, 86400, 3661])
    func roundTrip(seconds: Int) throws {
        let format = DurationFormat()
        #expect(try format.parseStrategy.parse(format.format(seconds)) == seconds)
    }

    @Test("a word list splits on commas and spaces")
    func words() {
        #expect(
            WordListFormat().parseStrategy.parse("github-actions, circleci  buildkite,") == [
                "github-actions", "circleci", "buildkite",
            ])
        #expect(WordListFormat().format(["github-actions", "circleci"]) == "github-actions, circleci")
    }
}
