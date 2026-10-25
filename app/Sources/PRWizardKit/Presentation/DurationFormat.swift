import Foundation

public struct DurationFormat: ParseableFormatStyle, Sendable {
    public enum Unit: Int, Codable, CaseIterable, Sendable {
        case hours = 3600
        case minutes = 60
        case seconds = 1

        var symbol: String { names[0] }

        var names: [String] {
            switch self {
            case .hours: ["h", "hr", "hrs", "hour", "hours"]
            case .minutes: ["min", "m", "mins", "minute", "minutes"]
            case .seconds: ["s", "sec", "secs", "second", "seconds"]
            }
        }
    }

    public struct Strategy: ParseStrategy, Sendable {
        struct Invalid: Error {}

        let bareUnit: Unit

        public func parse(_ text: String) throws -> Int {
            var rest = Substring(text.lowercased().trimmingCharacters(in: .whitespaces))
            guard !rest.isEmpty else { throw Invalid() }
            var total = 0
            while let match = rest.prefixMatch(of: /(\d+)\s*([a-z]*)\s*/) {
                let word = String(match.2)
                guard let count = Int(match.1),
                    let unit = word.isEmpty ? bareUnit : Unit.allCases.first(where: { $0.names.contains(word) })
                else { throw Invalid() }
                total += count * unit.rawValue
                rest = rest[match.range.upperBound...]
            }
            guard rest.isEmpty else { throw Invalid() }
            return total
        }
    }

    public let bareUnit: Unit

    public init(bareUnit: Unit = .minutes) {
        self.bareUnit = bareUnit
    }

    public var parseStrategy: Strategy { Strategy(bareUnit: bareUnit) }

    public func format(_ seconds: Int) -> String {
        var rest = seconds
        let parts = Unit.allCases.compactMap { unit -> String? in
            defer { rest %= unit.rawValue }
            let count = rest / unit.rawValue
            return count == 0 ? nil : "\(count) \(unit.symbol)"
        }
        return parts.isEmpty ? "0 s" : parts.joined(separator: " ")
    }
}
