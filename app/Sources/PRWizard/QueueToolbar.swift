import PRWizardKit
import SwiftUI

struct QueueToolbar: ToolbarContent {
    let store: QueueStore
    let repo: String?
    @Binding var showsInspector: Bool
    @Binding var search: String

    var body: some ToolbarContent {
        ToolbarItem(placement: .principal) { DaemonStatus(store: store, repo: repo) }
        ToolbarItem(placement: .primaryAction) { FilterField(text: $search) }
        ToolbarItemGroup(placement: .primaryAction) {
            let isPaused = store.snapshot?.isPaused == true
            if isPaused { pause(isPaused).buttonStyle(.borderedProminent) } else { pause(isPaused) }
            Button {
                Task { await store.refresh() }
            } label: {
                Label("Refresh", systemImage: "arrow.clockwise")
                    .symbolEffect(.rotate, options: .repeat(.continuous), isActive: store.isRefreshing)
            }
            .disabled(store.snapshot == nil || store.isRefreshing)
            .help(store.isRefreshing ? "Fetching the PRs from GitHub…" : "Fetch the PRs from GitHub now")
            Button {
                showsInspector.toggle()
            } label: {
                Label("Inspector", systemImage: "sidebar.trailing")
            }
            .help(showsInspector ? "Hide the inspector" : "Show the inspector")
        }
    }

    private func pause(_ isPaused: Bool) -> some View {
        Button {
            Task { await store.setPaused(!isPaused) }
        } label: {
            Label(isPaused ? "Resume" : "Pause", systemImage: isPaused ? "play.fill" : "pause.fill")
        }
        .disabled(store.snapshot == nil || store.pendingActions.contains(.setPaused(!isPaused)))
        .help(isPaused ? "Resume every lane" : "Pause every lane")
    }
}

private struct FilterField: View {
    @Binding var text: String

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "line.3.horizontal.decrease").foregroundStyle(.secondary)
            TextField("Filter", text: $text)
                .textFieldStyle(.plain)
                .onExitCommand { text = "" }
            if !text.isEmpty {
                Button("Clear", systemImage: "xmark.circle.fill") { text = "" }
                    .labelStyle(.iconOnly)
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 8)
        .frame(width: 200)
        .help("Filter by number, title or project (⌘F)")
    }
}

private struct DaemonStatus: View {
    let store: QueueStore
    let repo: String?

    var body: some View {
        switch store.phase {
        case .idle, .connecting: status("Connecting…", .neutral)
        case .incompatible: status("Incompatible daemon", .bad)
        case .down(_, let retryAt), .stale(_, _, let retryAt):
            HStack {
                status(
                    Text("Disconnected · retrying in \(Text(timerInterval: min(.now, retryAt)...retryAt))"), .attention)
                Button("Retry") { store.retry() }
            }
        case .live(let snapshot):
            if store.isRefreshing {
                status("Fetching PRs from GitHub…", .neutral)
            } else if let error = snapshot.refresh.lastError {
                status(
                    Text(
                        "GitHub fetch failed \(snapshot.refresh.lastAt?.formatted(date: .omitted, time: .shortened) ?? "")"
                    ), .attention
                )
                .help(error)
            } else if snapshot.isPaused {
                status("Paused", .neutral)
            } else {
                status(Text("Running · \(lane(.review, in: snapshot)) · \(lane(.fix, in: snapshot))"), .good)
            }
        }
    }

    private func lane(_ lane: Lane, in snapshot: QueueSnapshot) -> String {
        let pools = snapshot.lanes.pools.filter {
            $0.lane == lane && (repo == nil || !snapshot.lanes.isSeparate || $0.repo == repo)
        }
        return "\(lane.rawValue) \(pools.map(\.busy).reduce(0, +))/\(pools.map(\.workers).reduce(0, +))"
    }

    private func status(_ text: Text, _ tone: Tone) -> some View {
        Label {
            text.monospacedDigit()
        } icon: {
            Image(systemName: "circle.fill").font(.caption2).foregroundStyle(tone.color)
        }
        .labelStyle(.titleAndIcon)
    }

    private func status(_ text: LocalizedStringKey, _ tone: Tone) -> some View {
        status(Text(text), tone)
    }
}
