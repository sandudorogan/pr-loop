import Foundation

public enum DaemonLocation {
    public static let state = URL.homeDirectory.appending(path: ".local/state/pr-loop")
    public static let socket = state.appending(path: "api.sock")
    public static let labelFile = state.appending(path: "launchd-label")
    public static let label = "local.pr-loop"
}
