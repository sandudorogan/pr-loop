public enum FeedEvent<Value: Sendable>: Sendable {
    case value(Value)
    case failure(any Error, retryIn: Duration)
}
