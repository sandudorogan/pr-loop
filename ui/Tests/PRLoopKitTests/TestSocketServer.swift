import Darwin
import Foundation

struct TestSocketServer: Sendable {
    let path: String
    private let listener: Int32

    init(reply: Data?) throws {
        path = Self.temporaryPath()
        listener = try Self.bound(to: path)
        guard listen(listener, 1) == 0 else { throw POSIXError(.init(rawValue: errno) ?? .EIO) }
        Thread { [listener] in Self.serveOnce(listener, reply: reply) }.start()
    }

    static func stale() throws -> String {
        let path = temporaryPath()
        close(try bound(to: path))
        return path
    }

    static func temporaryPath() -> String {
        FileManager.default.temporaryDirectory.appending(path: "prw-\(UUID().uuidString.prefix(8)).sock").path()
    }

    func stop() {
        close(listener)
        unlink(path)
    }

    private static func bound(to path: String) throws -> Int32 {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutableBytes(of: &address.sun_path) { $0.copyBytes(from: path.utf8) }
        let result = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard result == 0 else { throw POSIXError(.init(rawValue: errno) ?? .EIO) }
        return fd
    }

    private static func serveOnce(_ listener: Int32, reply: Data?) {
        let client = accept(listener, nil, nil)
        defer { close(client) }
        var request = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while request.firstRange(of: Data("\r\n\r\n".utf8)) == nil {
            let count = read(client, &buffer, buffer.count)
            guard count > 0 else { return }
            request.append(contentsOf: buffer[..<count])
        }
        guard let reply else {
            while read(client, &buffer, buffer.count) > 0 {}
            return
        }
        _ = reply.withUnsafeBytes { write(client, $0.baseAddress, $0.count) }
    }
}
