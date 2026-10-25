public enum Backoff {
    public static func delay(_ attempt: Int) -> Duration {
        .seconds(min(2 << min(attempt, 4), 30))
    }
}
