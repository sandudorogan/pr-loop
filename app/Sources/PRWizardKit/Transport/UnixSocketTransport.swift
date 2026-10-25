import Foundation
import Network

public struct UnixSocketTransport: HTTPTransport {
    public let path: String

    public init(path: String) {
        self.path = path
    }

    public func send(_ request: HTTPRequest, timeout: Duration) async throws -> HTTPResponse {
        let connection = NetworkConnection(to: .unix(path: path)) { TCP() }
        let (states, continuation) = AsyncStream.makeStream(of: NetworkConnection<TCP>.State.self)
        connection.onStateUpdate { _, state in continuation.yield(state) }
        let data = try await withThrowingTaskGroup { group in
            group.addTask { try await Self.exchange(HTTPCodec.encode(request), over: connection) }
            group.addTask { try await Self.failOnWaiting(states) }
            group.addTask {
                try await Task.sleep(for: timeout)
                throw APIError.timeout
            }
            defer { group.cancelAll() }
            return try await group.next() ?? Data()
        }
        return try HTTPCodec.decode(data)
    }

    private static func exchange(_ bytes: Data, over connection: NetworkConnection<TCP>) async throws -> Data {
        do {
            try await connection.send(bytes)
            var data = Data()
            while true {
                let message = try await connection.receive(atMost: 1 << 16)
                data.append(message.content)
                if message.metadata.endOfStream { return data }
            }
        } catch let error as NWError {
            throw mapped(error)
        }
    }

    private static func failOnWaiting(_ states: AsyncStream<NetworkConnection<TCP>.State>) async throws -> Data {
        for await state in states {
            if case .waiting(let error) = state { throw mapped(error) }
        }
        throw CancellationError()
    }

    private static func mapped(_ error: NWError) -> any Error {
        switch error {
        case .posix(.ENOENT), .posix(.ECONNREFUSED): APIError.down
        default: error
        }
    }
}
