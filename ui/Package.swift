// swift-tools-version: 6.2
import PackageDescription

let strict: [SwiftSetting] = [
    .enableUpcomingFeature("NonisolatedNonsendingByDefault"),
    .enableUpcomingFeature("InferIsolatedConformances"),
    .enableUpcomingFeature("ExistentialAny"),
    .enableUpcomingFeature("MemberImportVisibility"),
]

let package = Package(
    name: "PRWizard",
    platforms: [.macOS(.v26)],
    targets: [
        .target(name: "PRWizardKit", swiftSettings: strict),
        .executableTarget(
            name: "PRWizard", dependencies: ["PRWizardKit"],
            swiftSettings: strict + [.defaultIsolation(MainActor.self)]),
        .testTarget(name: "PRWizardKitTests", dependencies: ["PRWizardKit"], swiftSettings: strict),
    ]
)
