// swift-tools-version: 6.2
import PackageDescription

let strict: [SwiftSetting] = [
    .enableUpcomingFeature("NonisolatedNonsendingByDefault"),
    .enableUpcomingFeature("InferIsolatedConformances"),
    .enableUpcomingFeature("ExistentialAny"),
    .enableUpcomingFeature("MemberImportVisibility"),
]

let package = Package(
    name: "PRLoop",
    platforms: [.macOS(.v26)],
    targets: [
        .target(name: "PRLoopKit", swiftSettings: strict),
        .executableTarget(
            name: "PRLoop", dependencies: ["PRLoopKit"],
            swiftSettings: strict + [.defaultIsolation(MainActor.self)]),
        .testTarget(name: "PRLoopKitTests", dependencies: ["PRLoopKit"], swiftSettings: strict),
    ]
)
