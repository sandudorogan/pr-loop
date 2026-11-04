extension SeverityCounts {
    public var nonZero: [(severity: Severity, count: Int)] {
        [(.critical, critical), (.high, high), (.medium, medium), (.low, low)].filter { $0.count > 0 }
    }
}
