import Foundation

public struct WordListFormat: ParseableFormatStyle, Sendable {
    public struct Strategy: ParseStrategy, Sendable {
        public func parse(_ text: String) -> [String] {
            text.split { $0 == "," || $0.isWhitespace }.map(String.init)
        }
    }

    public init() {}

    public var parseStrategy: Strategy { Strategy() }

    public func format(_ words: [String]) -> String {
        words.joined(separator: ", ")
    }
}
