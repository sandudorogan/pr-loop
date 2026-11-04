# PR Loop.app

PR Loop.app is the macOS UI of the PR Loop daemon. It shows the queue, edits the config and posts the
"Ready for your approval" notification. It is one client of the control API on `api.sock`. It never runs reviews
or fixes itself. Other OS UIs can come later. Each one is its own client of the same API (`docs/api.md`).

Read this file before you change `ui/`. `api.md` owns every wire shape: where this file names a field, `api.md` wins.

## 1. Toolchain

The owner's machine has the Command Line Tools only. There is no Xcode.

| Item | Value | Consequence |
| --- | --- | --- |
| Developer dir | `/Library/Developer/CommandLineTools` | no `xcodebuild`, no `.xcodeproj`, no XCTest, no asset catalogs |
| Swift | 6.x, tools-version 6.2, Swift 6 language mode | strict concurrency everywhere |
| Platform | macOS 26.0 deployment target, Apple silicon | macOS 26 APIs (`NetworkConnection`, `Tab`, Liquid Glass) |
| Tests | `Testing.framework` ships in the CLT | Swift Testing only |
| Format | `swift format` (bare `swift-format` is not on PATH) | the formatter and the linter |

Hard rules:

- **Never run plain `swift test`.** Under the CLT it builds the tests, runs zero, and exits 0. `ui/script/test`
  adds `-Xswiftc -F <CLT>/Library/Developer/Frameworks` and the rpaths. The same flags in `Package.swift` do not help.
- **No SwiftUI macros.** The CLT has no `SwiftUIMacros` plugin, so `@Entry` fails. Write `FocusedValueKey` and
  `EnvironmentKey` by hand (see `ui/Sources/PRLoop/FocusedValues+QueueFocus.swift`).
- **No dependencies.** Apple frameworks only: SwiftUI, AppKit, Network, Observation, ServiceManagement, UserNotifications.

## 2. Conventions

A reviewer rejects a change that breaks one of these.

| Topic | Rule |
| --- | --- |
| Language | Upcoming features on every target: `NonisolatedNonsendingByDefault`, `InferIsolatedConformances`, `ExistentialAny`, `MemberImportVisibility` (`ui/Package.swift`). |
| Isolation | App target: `.defaultIsolation(MainActor.self)`. `PRLoopKit`: nonisolated by default. Stores are `@MainActor @Observable final class`. Models are `Codable, Sendable, Hashable` structs. Transport and client are `Sendable` structs. |
| Concurrency | `async`/`await` only. No `DispatchQueue`, completion handlers, `Task.detached`, `@unchecked Sendable` or `nonisolated(unsafe)`. A store owns its long-lived `Task` and cancels it in `stop()`. Cancellation closes the socket. |
| Observation | `@Observable` with `@State`, `@Environment(Type.self)`, `@Bindable`. No `ObservableObject`, no Combine. |
| Identity | A PR is `PRRef(repo:number:)`. Its `id` is the wire `key` (`"iprally/iprally#17190"`). PR numbers repeat across repos, so tables, selection, actions and notifications never key on a bare `Int`. |
| Wire models | Explicit `CodingKeys`, no key strategy. Open enums (`api.md §1`) carry `unknown(String)`: a new value never fails a decode. Status strings stay `String`; `StatusStyle` owns that vocabulary. |
| Naming | Swift API Design Guidelines. Booleans read as assertions (`isDraft`, `showsMenuBarExtra`). No `Manager`, `Helper`, `Util`. |
| Files | One type per file, named after the type. Extensions: `Type+Purpose.swift`. A view can keep small `private` subviews in its file. |
| Safety | No `!`, `try!`, `as!` or IUO. Tests use `try #require(…)`. swift-format enforces it. |
| Comments | Only where the logic is not obvious, as Google-style docstring prose. No file headers. |
| UI | System components only: `Table`, `Form` `.formStyle(.grouped)`, `ContentUnavailableView`, `Label`, SF Symbols. Colors come from the semantic `Tone` (`neutral`, `working`, `good`, `info`, `caution`, `attention`, `bad`). No custom fonts. |
| Accessibility | An icon-only control has a `Label` or `.accessibilityLabel`. Color is never the only signal: a badge is symbol + text. Every toolbar action has a menu command and a shortcut. `.help` on toolbar items. |
| Text | `Text("#\(n)")` formats the `Int` by locale (`#17.190`). Use `Text(verbatim:)` for numbers and ids. |
| Resources | No SwiftPM `resources:` in shipping targets. Tests read fixtures by path. |
| Format | `ui/.swift-format`: 4 spaces, line length 120, `NeverForceUnwrap`, `NeverUseForceTry`, `NeverUseImplicitlyUnwrappedOptionals`, `OrderedImports`, `UseLetInEveryBoundCaseVariable`. Never write a partial `rules` map: it replaces the defaults (5 rules on instead of ~40). |
| Notifications | Exactly one kind: "Ready for your approval" on a colleague's PR (§6.6). Do not add more. |

## 3. Package layout

One SwiftPM package at `ui/`. XcodeGen and Tuist only make projects for `xcodebuild`, so they add nothing here.

```text
ui/
├── Package.swift            PRLoopKit (library) · PRLoop (executable) · PRLoopKitTests
├── .swift-format
├── Resources/               Info.plist (bundle id local.pr-loop.app) · AppIcon.icns (script/icon)
├── script/                  test · lint · bundle · run · install · contract · package · notes · icon
├── Sources/
│   ├── PRLoopKit/         models, transport, client, feeds, stores, presentation. No SwiftUI.
│   └── PRLoop/            App, scenes, views, system adapters. Thin: no logic a test needs.
└── Tests/PRLoopKitTests/  Swift Testing; fixtures from contract/api/v1/ at the repo root
```

The split is the design. Every decision a test can check lives in `PRLoopKit`: what a row shows, which action is
on, which marker a setting gets, what a patch holds. A view reads a Kit value and draws it.

## 4. Build, run, install, release

All commands run from `ui/`.

| Task | Command |
| --- | --- |
| Test | `script/test` · one suite: `script/test --filter QueueStoreTests` |
| Coverage | `script/test --enable-code-coverage`, then `swift test --show-codecov-path` |
| Lint | `script/lint` · fix: `swift format --in-place --recursive Sources Tests` |
| Contract | `script/contract`: the fake daemon on a temp socket, then `ContractTests` against it |
| Bundle | `script/bundle` → `build/PR Loop.app` (release build, `Info.plist`, icon, ad-hoc sign, verify) |
| Run | `script/run` · against a fake: `script/run -- -socket /tmp/prw.sock` |
| Fake daemon | `python3 -m pr_loop.api --fake --socket /tmp/prw.sock` (from `daemon/`; `api.md §7`) |
| Install | `script/install` → `/Applications/PR Loop.app` |
| Package | `VERSION=X.Y.Z script/package` → `build/PR-Loop-X.Y.Z.{dmg,zip}` + `build/SHA256SUMS` |
| Notes · icon | `script/notes vX.Y.Z` (release body) · `script/icon` → `Resources/AppIcon.icns` (commit it) |

- The version is `1.0.<commit count>` unless `VERSION` is set. `CFBundleVersion` is the commit count.
- `-socket <path>` overrides the socket path with no code: `UserDefaults` reads `-key value` launch arguments.
- `script/install` quits the installed copy by binary path, deletes it (`ditto` merges and keeps stale files), then
  copies the new bundle. It targets `/Applications` because `~/Applications` is root-owned on the owner's machine.
- A `v*` tag push runs `.github/workflows/release.yml`: test + lint, package, notes, `gh release create`. The
  release is ad-hoc signed and not notarized; the notes tell the user how to pass Gatekeeper.

## 5. Architecture

```text
 views (PRLoop) ──@Environment──▶ stores (PRLoopKit, @MainActor @Observable)
                                      │ QueueStore · HistoryStore · SettingsStore · PRSettingsStore · ReadyNotifications
                                      ▼
                                    DaemonClient : DaemonAPI        one method per endpoint, PRRef → path
                                      │ HTTPRequest / HTTPResponse  (HTTPCodec: Content-Length, Connection: close)
                                      ▼
                                    UnixSocketTransport : HTTPTransport   NetworkConnection(.unix), read to EOF
                                      │ HTTP/1.1 + JSON, one request per connection
                                      ▼
                     ~/.local/state/pr-loop/api.sock ── the one daemon (launchd local.pr-loop), every repo
```

- `AppDelegate` (`ui/Sources/PRLoop/AppDelegate.swift`) builds one `DaemonClient` and every store on it. It
  calls `store.start()` and `notifications.start()` in `applicationDidFinishLaunching`. State restoration can
  launch the app with the main window closed, so a window `.task` must not start a feed.
- The app talks to the daemon through the API only. It never reads `state.db`, never runs the `pr-loop` CLI, and
  never runs git or chezmoi. A GUI app gets a minimal PATH in which `/usr/bin/python3` is too old.
- **Start Daemon** runs `/bin/launchctl kickstart gui/<uid>/<label>` through `DaemonLauncher`
  (`ui/Sources/PRLoopKit/Daemon/DaemonLauncher.swift`). The label is the one line of
  `~/.local/state/pr-loop/launchd-label`, which survives a stop. Without the file it is `local.pr-loop`.
  Paths live in `DaemonLocation`.

**Seams.** Every system or daemon edge is a Kit protocol. Tests fake the protocol, never the store.

| Protocol | Real | Fake (tests) |
| --- | --- | --- |
| `HTTPTransport` | `UnixSocketTransport` | `FakeTransport` (records requests, canned responses) |
| `DaemonAPI` | `DaemonClient` | `ScriptedDaemon` |
| `Notifier` | `UserNotificationsNotifier` (app) | `FakeNotifier` |
| `EventCursor` | `DefaultsEventCursor` (app) | `MemoryCursor` |
| `DaemonLauncher` | `ProcessDaemonLauncher` (app) | a recording `run` |
| `LoginItemService` | `SMAppService` extension (app) | a scripted status |

**Errors.** `APIError` (`ui/Sources/PRLoopKit/APIError.swift`): `.down` (ENOENT, ECONNREFUSED), `.timeout`,
`.http(status:code:message:details:)`, `.decoding`, `.incompatible(api:)`. Views switch on it. No string errors.

- `NetworkConnection` waits forever on a missing or stale socket. `UnixSocketTransport` checks ENOENT and
  ECONNREFUSED first and throws `.down` at once.
- The codec rejects chunked bodies and 204/304 (`api.md` forbids them). Timeout: 10 s, or `wait + 10 s` for a long-poll.

### 5.1 Live updates

The queue and the events use one loop, `LongPoll<Value>` (`ui/Sources/PRLoopKit/Feeds/LongPoll.swift`).
A store never sees the transport.

```text
 connect(cursor)  ─ wait=0 ─▶ yield the value                          QueueFeed: GET /v1/info + /v1/queue
      │                                                                EventFeed: GET /v1/events?since=<saved>
      ▼
 loop: poll(cursor) GET …?since=<cursor>&wait=55
        ├─ ok    ─▶ yield when the cursor moved ; cursor = next ; attempt = 0
        └─ error ─▶ yield .failure(retryIn: Backoff.delay(attempt)) ; sleep ; reconnect
                    Backoff: 2, 4, 8, 16, 30, 30 … s
```

- `GET /v1/info` runs once per connect. Pools, projects, pause state and refresh state come in the snapshot.
- Actions (`refresh`, `next`, `review`, `fix`, `pause`) do not refetch. The daemon wakes every long-poller on a write.
- `sleep` is injected, so tests run the loop with no real waits.

### 5.2 QueueStore phases

```text
           start()
  idle ──────────────▶ connecting ───first snapshot───▶ live(snapshot)
                           │                              │  ▲
                   error   │                     failure  │  │ next snapshot
                           ▼                              ▼  │
                     down(error, retryAt) ◀──────── stale(snapshot, error, retryAt)
                           └──────────── snapshot ─────────────▶ live
  info.api ≠ 1 ──▶ incompatible(api)   (terminal)
```

- `stale` keeps the last table, dimmed to 50 %. `Phase` holds `any Error`, so it is not `Equatable`.
- `pendingActions` (action + `PRRef`) disables a control while its request runs. A failure sets `lastActionError`:
  a bottom banner that a separate task clears after 6 s. No alerts for routine failures.
- `projects: [ProjectSummary]` (short name, status, lane line, ready count, pools) feeds the sidebar, the scope
  picker and the menu commands.

## 6. Scenes

`ui/Sources/PRLoop/PRLoopApp.swift` declares three scenes: the `Window` "PR Loop" (id `queue`), `Settings`
and the `MenuBarExtra`. The activation policy is `.regular`. Closing the window keeps the app running while the
menu bar extra is on. With it off, the app quits (`applicationShouldTerminateAfterLastWindowClosed`).

### 6.1 Main window

```text
┌─ toolbar ─────────────────────────────────────────────────────────────────────────────────────────┐
│ ● ● ●  [sidebar]  PR Loop            ● Running · review 1/3 · fix 0/3    [Filter…] ⏸  ⟳  [inspector] │
│                   All repos · fetched 12:00                                                        │
├──────────────────┬──────────────────────────────────────────────────────────┬─┬──────────────────┤
│ All repos      4 │    PR     Project  Title                Author  Status   Detail │▏│ Status       ⚙   │
│ Repos            │ In Work                                                  │▏│ iprally #17190   │
│ iprally/iprally 3│ ▶  #17190 iprally  feat(search): keep…  you     Reviewing 02:08 │▏│ Live run         │
│   review · fix   │ Up Next                                                  │▏│ Review           │
│ iprally/gitops  1│ 1  #17201 iprally  fix(api): retry…     colleague Queued  …     │▏│ Findings         │
│   fix only       │ Ready · Waiting · Paused                                 │▏│ Fix              │
└──────────────────┴──────────────────────────────────────────────────────────┴─┴──────────────────┘
   NavigationSplitView sidebar        detail = HStack [ table | ResizeHandle | PRInspector ]
```

| Element | Rule |
| --- | --- |
| Sidebar | `ProjectSidebar`: "All repos" with the total ready badge, then a "Repos" section in the snapshot's order. A row shows `owner/name` (middle-truncated), the lane line and the ready badge. `error` and `no-checkout` rows show a warning badge; `.help` gives the reason. They stay selectable: their PRs are real `skipped` rows. Selection is `@SceneStorage("sidebar")`. ⌘0 selects All repos, ⌘1…⌘9 the nth repo. |
| Sidebar toggle | Our own button in the sidebar's toolbar. The system toggle is removed (`.toolbar(removing: .sidebarToggle)`) because it shows no on state. It drives `NavigationSplitView(columnVisibility:)` from `@SceneStorage("sidebarShown")`. |
| Sections | From `group` (`QueueSection`): In Work (`active`), Up Next (`queued`), Ready, Waiting (`idle`, unknown), Paused. Empty sections hide. |
| Order | The daemon's `items` order, filtered by the sidebar and the filter. No column sort: the order is the review priority. Ranks come from the daemon. The app ranks nothing. |
| Columns | mark (▶ / rank / ✓ / pause) · PR · Project (All repos only) · Title (`[Draft]` tag) · Author (`you` when `mine`) · Status (badge + override cue) · Detail (a timer while `active`). Minimums sum to `QueueTable.minWidth` = 566 pt. Customization is `@SceneStorage("columns")`. |
| Selection | Multi, keyed by `PRRef.id`. ⏎ or double-click opens the PR. **A non-empty selection opens the inspector.** Deselect leaves it as it is. |
| Override cue | `items[].override` non-empty → `slider.horizontal.3` after the status badge, with the paths in `.help` and the accessibility label. |
| Toolbar | Principal: daemon status (Running · review busy/workers · fix busy/workers, Paused, Fetching, GitHub fetch failed, Disconnected + Retry). With `lanes.separate` and one repo selected, it counts that repo's pools. Trailing group, in this order: Filter, Pause/Resume (the selected PRs), Refresh, Inspector toggle. |
| Filter | A plain `TextField` in a `.primaryAction` toolbar item (`FilterField`), placed before the buttons, so NSToolbar overflows the buttons first. It matches number, title or project. Esc clears it. ⌘F calls `NSWindow.focusToolbarField()`. |
| Inspector | A column in the detail `HStack`, after a `ResizeHandle`. Width is `@SceneStorage("inspectorWidth")`, from 280 pt up to what leaves the table its 566 pt. Shown state is `@SceneStorage("inspector")`. |
| Window minimum | SwiftUI drops a minimum on the detail column, so the window carries it: `max(820, sidebar 228 (when shown) + 566 + inspector + 1)`. Opening the inspector in a narrow window grows the window. |

**Commands.** `PullRequestMenu` is one view for the Pull Request menu, the row context menu and the inspector's
Actions menu. `ActionAvailability` (Kit) enables each action and gives the reason for a disabled one.

| Menu | Items |
| --- | --- |
| Pull Request | Open on GitHub ⌘O · Copy Link ⇧⌘C · Move to Front ⌘] · Review Now ⇧⌘R · Retry Fix ⇧⌘F · Pause/Resume ⇧⌘P · Show Findings ⌘Y · PR Settings… ⇧⌘, · Copy Head SHA |
| View | Show/Hide Sidebar · Show/Hide Inspector ⌥⌘I · Refresh ⌘R · All Repos ⌘0 · repo 1…9 ⌘1…⌘9 |
| Edit | Filter ⌘F |
| Daemon | Pause/Resume all ⌥⌘P · Start Daemon · Open Log |

- Review Now needs: not active, the project `available`, its review lane on. Retry Fix also needs `mine` and no
  `no-auto-fix` label. Otherwise the daemon answers 409; the app disables the item first.
- Pause in the toolbar and in the Pull Request menu acts on the selected PRs (`api.md §3.17`). It resumes only when
  every selected PR is paused. The Daemon menu pauses every lane (`api.md §3.12`).
- Menu commands read the focused window's state through `focusedSceneValue` (`QueueFocus`, `PeekFocus`).

**Findings peek.** A popover on the selected row's Status cell, arrow on the trailing edge. Space (`onKeyPress` on
the table) or ⌘Y toggles it. Esc and a scroll dismiss it. `PeekModel` holds only `shownID`. Space passes through
unless exactly one row with findings is selected, so Space still types in the Filter field. There is no hover
trigger. VoiceOver reads `accessibilityCustomContent` on the row: "Findings", "At fix floor", "Top finding".
`FindingsView` draws the content: round, short head, "N at or above the fix floor", one row per reviewer (result
word, severity capsules, link), and the daemon's `top` (≤ 3). `SeverityStyle` gives symbol + tone per severity.

**Inspector.** One selected PR shows a header bar ("Status" or "PR Settings", a button to switch) and the tab.
None or many selected: "No Selection" / "Multiple Selection". The tab is `@SceneStorage("inspectorTab")` on
`QueueWindow`, so "PR Settings…" can select the row, open the inspector and switch the tab. The Status tab shows
the header, an Actions menu, Live run (lane, timer, reviewer states), Review, Findings (with all followed
convention files) and Fix. Its strings come from `InspectorModel`.

### 6.2 Empty, loading and error states

The table area shows these. The toolbar stays usable.

| State | The table area shows |
| --- | --- |
| connecting, no snapshot | `ProgressView` "Connecting to PR Loop…" |
| down, never connected | "PR Loop is not running", socket path, last error · Start Daemon · Retry |
| stale | the last table, dimmed; the toolbar says Disconnected |
| incompatible | "The daemon speaks API vN. This app speaks v1." |
| empty queue, or no rows in the selected repo | "Recently worked on": `HistoryTable` from `GET /v1/history?limit=20&repo=` (`api.md §3.13`) |
| empty queue, no history | `ContentUnavailableView` "Nothing in the queue" |
| filter with no match | `ContentUnavailableView.search(text:)` |

`HistoryStore.show(repo:rev:)` is the whole refetch rule. The view calls it with `.task(id: (repo, rev))`. The same
`(repo, rev)` as the last good fetch does nothing. A cancelled fetch applies nothing. History has no long-poll: it
only grows when the queue `rev` moves.

### 6.3 Settings (⌘,)

`SettingsView` is a `TabView` of four `Tab`s. The last pane is `@AppStorage("settingsPane")`. Each pane has a
fixed width and fits its height.

| Pane | Width | Scoped | Holds |
| --- | --- | --- | --- |
| General | 560 | no | menu bar extra, Open at login, notifications, daemon status (Reveal Config, Open Log, Pause, Start) |
| Lanes | 600 | yes | `review.enabled`, `fix.enabled`, workers, review gates; All repos also: `lanes.separate`, `detect.roots`, `refresh` |
| Reviewers | 720 | yes | `review.reviewers` (master-detail list + `ReviewerForm`), the conventions line |
| Fixer | 600 | yes | `fix.*` except `enabled` and `workers`, the gates list and editor, the conventions line |

**Scope.** `ScopedPane` puts the scope dropdown first, then banners, then the pane, then the `ApplyBar`. The scope
is shared by the three panes (`@AppStorage("settingsScope")`). Items: "All repos", a divider, then the snapshot's
projects. A `no-checkout` project is disabled. An `error` project stays enabled and shows its error as a banner.
The menu marks a scope with unsaved edits (pencil) or 422 errors (warning).

- `ScopePicker` is a `Menu` of `Toggle`s, not a `Picker`: a menu-style `Picker` ignores `.disabled` on items.
- A pane shows the selected scope only. Global keys appear in All repos only.
- `SettingRow(key:scope:)` = control + `OverrideMarker` + field error. In a project scope the marker reads
  "Default" or "Overridden" with **Use Default** (`arrow.uturn.backward`).
- Lists (`reviewers`, `trivial`, `gates`) override whole. In a project scope a "Use the default …" toggle guards
  them. Turning it off copies the default list into the override. The copy is then edited.
- Row logic lives in Kit: `LanesLayout` (which worker rows show, per scope × `separate` × project status),
  `WorkerTotals` (machine total from the draft, warning above 8 in either lane), `ReviewerSummary`, `EffortChoices`,
  `ConventionsLine`, `GateList`, `GateDraft`.
- Every picker reads `config.choices`. No hard-coded model lists. A `null` Codex model reads from `codex_default`.
- Gates keep config order. The daemon runs them in array order. A new gate, or one whose kind changed, lands at the
  end of its kind, so format gates stay before test gates.
- `GateDraft` checks regexes with `NSRegularExpression` after it rewrites `(?P<n>` and `(?P=n)`. ICU and Python
  differ at the edges, so the daemon's 422 on Apply stays the final check.

**General › Notifications** shows a fix-it row when System Settings has PR Loop off ("Open…"), and when the alert
style is not Persistent (`NotificationAuthorization.temporary`). `Info.plist` sets `NSUserNotificationAlertStyle =
alert`, so Persistent is the default at the first registration.

**General › Open at login** is `SMAppService.mainApp` behind `LoginItemService`. The toggle re-reads the status when
the app becomes active. A never-registered app reports `.notFound`. Registration survived a rebuild with a new
ad-hoc signature.

### 6.4 Per-PR settings

The PR level lives in the inspector, not in Settings: it is a property of the selected row. `PRSettingsTab` fills
the inspector's Settings tab.

```text
 defaults ("All repos")   config file   ┐
   ⊕ projects["o/n"]      config file   ├─ Settings window: one draft, explicit Apply       (§7)
   ⊕ PR override          state.db      ── inspector: live, one request per change         (api.md §3.14–3.16)
   ⊗ labels               GitHub        ── read-only; can only turn a lane off
   = effective
```

| Rule | |
| --- | --- |
| Data | `GET …/config` → `rev`, `override`, `layers {project, pr}`, `labels`, `effective`. The tab shows `effective`. `PRSettingsStore` keeps the last response; every write replaces it. No draft and no resolver. |
| Store | One `PRSettingsStore` per window. `show(_:)` resets on a new PR and drops answers for another PR. The tab calls it with `.task(id: (ref, labels, override))`, so a change from another client reloads on the next snapshot. |
| Markers | `PRMarkers` from `layers` and `labels`: `.pr` → Overridden + Use Default · `.project(repo)` → "Inherited from repo" · `.default` · `.label(name)` → "Label no-auto-review on GitHub", control disabled. A label wins for `*.enabled`. A section header asks with all its paths and gets the strongest source. |
| Writes | Serial. `isWriting` disables the form. A write that arrives during another is dropped: a second request on the same `rev` would only 412. |
| 412 | Reload, show "Changed elsewhere, reloaded". The change is not retried. |
| 422 | `problems`; `messages(at:)` matches the path, `path.…` and `path[…]`. |
| 404 | `not_in_queue` or `unknown_repo` → "This PR is no longer in the queue", no controls. |
| Reviewers | Rows edit enable, model and effort with pickers (no text fields: a live write per keystroke would save half a name). Each edit sends the whole effective list. "Edit all reviewer fields…" edits a copy in `ReviewerForm` and Done writes it once. |
| Fixer | Model, effort, prompts, gates on/off, limits, timeouts. No `workers`. A gate has no `enabled` key: off means the PR's `fix.gates` lists the project's gates without it. All on again → Use Default. |
| Use Default (whole PR) | `DELETE …/config`. It asks first when more than one setting is overridden. |

**PATCH vs PUT at the PR level.** A merge patch cannot store a `null`: `null` deletes the key.

```text
 picker value            request                                   result
 ─────────────────────   ───────────────────────────────────────   ──────────────────────────────────
 a value                 PATCH {base_rev, patch: {path: value}}    PR overrides the key
 Use Default (marker)    PATCH {base_rev, patch: {path: null}}     key deleted → inherits project/defaults
 "default" (null) pick   PUT   {base_rev, override: <whole, path   explicit null kept → the built-in
                                = null>}                           default wins over a project value
```

`PRSettingsStore.set(_:to:)` picks the request. Both requests are `api.md §3.15`.

### 6.5 Menu bar extra

`MenuBarExtra("PR Loop", systemImage: "arrow.triangle.2.circlepath", isInserted:)` with `.menuBarExtraStyle(.menu)`.
`showsMenuBarExtra` defaults to true through `register(defaults:)`, because the quit rule reads `UserDefaults.bool`.

- Top 5 = the first five `items` across every repo, in the daemon's order (`MenuItems.top(_:in:)`), title cut at 44
  characters. It ignores the sidebar: the extra is a glance at the whole system. `stale` shows as down, because old
  rows would look current.
- Open PR Loop (⌘O) and Settings… (⌘,) call `NSApp.activate()`, then `openWindow(id: "queue")` or `openSettings()`.
  No bridge window is needed: Settings… opened with the main window open, closed and hidden.

### 6.6 Notifications

The daemon has no UI. It records `ready_for_approval` (a colleague's PR reviewed READY) and `ready_withdrawn`
(a new head on it) for `GET /v1/events` (`api.md §3.3`). `ReadyNotifications` turns them into the one notification.

```text
 launch ── cursor = EventCursor.lastSeen()
   │ nil (first launch) ──▶ GET /v1/events (no since) ──▶ save cursor, post nothing ("subscribe from now")
   ▼
 connect: GET /v1/events?since=<cursor>&wait=0 ── + GET /v1/queue ──▶ CatchUp.plan ──▶ post/remove ──▶ save
   ▼                                              (only when the page has events)
 poll:    GET /v1/events?since=<cursor>&wait=55 ──▶ LivePlan.plan ──▶ post/remove ──▶ save   (forever)
          reset: true page ──▶ treated as a catch-up (daemon restart between two polls)
```

- Per `key`, the highest `seq` wins. `ready_for_approval` → post. `ready_withdrawn` → remove every delivered
  notification with that `key` (any head). Catch-up also needs the `key` in `ready` at the same `head` in the snapshot.
- Content (`ReadyNotification`): subtitle "iprally #17166 · author · notes only", body = PR title, identifier =
  event `id`, thread = `key`, `userInfo` = `url` + `key`.
- At least once: the cursor saves only after the ops ran, and a failed post carries into the next page. The store
  skips ids it posted this session, because re-adding a delivered id presents it again.
- Toggle off or not authorized: the cursor moves, removes run, nothing posts. `authorize()` runs on the toggle's
  change and on `applicationDidBecomeActive`, and requests at most once per launch.
- The `UNUserNotificationCenter` delegate is set in `applicationWillFinishLaunching`, so a click that launches the
  app reaches `didReceive`, which opens `userInfo["url"]`. `willPresent` returns `[.banner, .list]`.
- Against the fake, `POST /v1/refresh` appends a `ready_for_approval` event (`api.md §7`).

## 7. Settings data flow

The Settings window edits two levels (defaults and projects) of one config file through one draft.

```text
 SettingsStore.load() ── GET /v1/config ──▶ original (ConfigEnvelope) ; base = rawConfig (JSON, key order kept)
                                             draft = OverrideResolver(base)        one tree, every scope
 edit:   set(key, to:, in: scope)  ·  useDefault(key, in:)  ·  setUsesDefault(_:for:in:)    dotted keys
 dirty:  patch = ConfigPatch.diff(base, draft)  (RFC 7396; objects recurse, arrays and scalars replace whole)
 Apply ─┬─ patch expressible ──▶ PATCH /v1/config {base_rev, patch}     (api.md §3.6)
        └─ patch has a null under projects where the draft holds an explicit null
                              ──▶ PUT   /v1/config {base_rev, config}    (api.md §3.5)
   200 ─▶ base = response ; savedTo = real_path ─▶ ApplyBar: "Saved to the chezmoi source. Commit your dotfiles…"
   412 stale_config   ─▶ banner "changed outside this window" [Reload]; the draft stays until Reload
   422 invalid_config ─▶ FieldErrors by path (projects["o/n"].fix.workers) ─▶ caption under the field,
                         or the pane banner when no field claims the path
 Revert ─▶ draft = base
```

- **Dotted keys under a scope** are the one vocabulary: `store.resolve("review.workers", in: scope)`, markers, 422
  paths and Use Default all use it. `.allRepos` writes top-level `review` / `fix` and the global keys. A project
  scope writes `projects["owner/name"].review.*` / `.fix.*`.
- **Use Default** removes the key from the project override and prunes the objects it empties. The patch sends
  `null`, so an emptied override goes out as `projects["o/n"]: null`.
- **Explicit null.** A project can say "Codex default" (`fix.model: null`) over a top-level model. PATCH cannot
  carry that, so the store sends PUT. Every other edit, top-level nulls included, stays PATCH.
- **Key order.** `JSONDecoder` and `JSONEncoder` drop it. The config goes through `JSONValue(parsing:)` and `.data`
  (an ordered `JSONObject`), so a save keeps the file's order. Typed models inside arrays (`ReviewerConfig`,
  `GateConfig`, …) keep unknown keys in `unknown`, because a patch replaces the whole array.
- Apply is explicit: one Apply is one validated write of a file the owner commits, and a reviewer edit spans
  several fields. App-local settings (General) apply at once. The draft outlives a closed Settings window.

**Where each setting lives**

| Lives in | Settings |
| --- | --- |
| `@AppStorage` (`AppStorageKey`, domain `local.pr-loop.app`) | `showsMenuBarExtra`, `notifiesReady`, `settingsPane`, `settingsScope`, `socket`, `eventCursor` (no UI) |
| `@SceneStorage` | `sidebar`, `sidebarShown`, `columns`, `inspector`, `inspectorTab`, `inspectorWidth` |
| System | Open at login (`SMAppService`) · notification permission and alert style (`UNUserNotificationCenter`) |
| Daemon `state.db` | per-PR overrides (`pr_overrides`), via `…/prs/{o}/{n}/{N}/config` |
| Config file (chezmoi source) | defaults, `projects[…]` overrides, `lanes.separate`, `detect.roots`, `refresh`, via `/v1/config` |

## 8. Testing

Swift Testing only: `@Suite`, `@Test("reads as a sentence")`, `#expect`, `try #require`, `@Test(arguments:)` for
tables. Store tests are `@MainActor`. Tests never touch the live daemon, `~/.local/state` or the real
notification center.

| Layer | What | How |
| --- | --- | --- |
| Models | every `contract/api/v1/*.json` decodes; unknown fields and enum values survive | `Fixture` reads the repo-root fixtures by `#filePath`. The Python tests (`daemon/tests/test_api_read.py`) assert the same files. |
| Codec | request bytes, response parse, chunked rejected | byte fixtures |
| Client | method, path, query, body per endpoint; `PRRef` in the path; error bodies → `APIError` | `FakeTransport` |
| Socket | 200, 4xx, ENOENT and refused → `.down`, timeout | `TestSocketServer` (POSIX socket in `$TMPDIR`) |
| Feeds | cursor threading, backoff 2…30, cancellation | `ScriptedDaemon` + recording sleeper |
| Stores | every phase, pending actions, 409 banner; settings dirty/revert/apply 200/412/422, scopes, Use Default, PATCH vs PUT; PR settings markers, writes, 412, 422, DELETE, gone; history refetch rule | `ScriptedDaemon` |
| Resolver oracle | `OverrideResolver` on `config.json` equals the daemon's `effective` for every project; patches checked with `merge_patch` | `contract/oracle/config.json` |
| Notifications | catch-up, live, cursor, permission, content | `FakeNotifier`, `MemoryCursor`, `events.json` |
| Presentation | `StatusStyle`, `SeverityStyle`, `ActionAvailability`, `ConfigPatch`, `ReviewerSummary`, `WorkerTotals`, `LanesLayout`, `ConventionsLine`, `GateDraft`, `MenuItems`, `FindingsSpeech`, … | pure, parameterized |
| Contract | the real `DaemonClient` against `python3 -m pr_loop.api --fake`, every endpoint | `script/contract` sets `PR_LOOP_CONTRACT_SOCKET`; `ContractTests` is disabled without it |

- Run the suite a change touches: `script/test --filter <Suite>`. Run `script/contract` after any wire-shape change,
  on either side.
- Coverage target: `PRLoopKit` ≥ 85 % lines. The app target is not measured.
- Not tested: SwiftUI view bodies and the thin adapters (`UserNotificationsNotifier`, `ProcessDaemonLauncher`,
  `SMAppService+LoginItemService`). XCUITest needs Xcode, and snapshot libraries need XCTest. Keep logic out of them.

## 9. Gotchas

**SwiftUI on macOS 26**

- **No `@Environment(Model.self)` in a table cell.** A `Table` with a conditional `TableColumn` (Project) rebuilds
  its cells without the window's environment when the column set changes, and the lookup traps. Read the model in
  the table view and pass it in (`QueueTable` does this with `PeekModel`).
- **No `.inspector`.** It floats over the table in a narrow window. `HSplitView` lays a SwiftUI child out at its
  `maxWidth`, so the content clips. Keep the `HStack` column and `ResizeHandle`.
- **No `.searchable`.** macOS 26 puts it last, after its own flexible space: with the inspector open it sat over the
  inspector and grew from 37 to 325 pt. `.toolbarPrincipal` and `DefaultToolbarItem(kind: .search)` do not help.
- **No `@FocusState` in a toolbar item.** It never takes focus there. Use `NSWindow.focusToolbarField()`.
- **No modifier-free key equivalents in menus.** They steal the key from text fields. Space is `onKeyPress` on the
  table, and it returns `.ignored` unless it acts.
- The detail column runs under the sidebar. `frame(minWidth:)` on it counts the sidebar twice, and
  `navigationSplitViewColumnWidth` on the detail does nothing. The window minimum carries the width (§6.1).
- A menu-style `Picker` ignores `.disabled` on items. Use a `Menu` of `Toggle`s.
- `Text(timerInterval:)` ticks to "0:00" at a retry boundary. That is not a bug.
- `Binding(set: store.setOn)` (a method reference on a `@MainActor` class) crashes swift-frontend 6.3 in IRGen.
  Write `{ store.setOn($0) }`.

**Notifications and system**

- `ready_withdrawn` carries the new head. Remove by `key`, never by the ready event's head.
- `NSUserNotificationAlertStyle = alert` sets Persistent only at the first registration. After that the owner's
  System Settings choice wins; General shows the fix-it row.
- macOS 26 draws its own glass rim around the icns in Finder and the Dock.

**Agent checks.** An agent shell cannot activate the app (`NSApp.isActive` stays false): no key window, no focused
values, no key events, no `screencapture`. Drive the app against `python3 -m pr_loop.api --fake --fake-speed 0
--socket /tmp/<x>.sock` and probe in process with an uncommitted file called from `applicationDidFinishLaunching`.

- Host a view in its own `NSWindow` (`isReleasedWhenClosed = false`, or `close()` crashes) and `cacheDisplay`
  `contentView.superview`. It does not draw Liquid Glass or a segmented picker.
- `showSettingsWindow:` does nothing under SwiftUI: perform the app menu's "Settings…" item. SwiftUI menus fill
  lazily: call `menu.delegate?.menuNeedsUpdate?(menu)` and `menu.update()` first.
- SwiftUI's split is not an `NSSplitViewController`: read the `NSSplitView`s in the frame view. A cell's AX custom
  content answers `value(forKey: "accessibilityCustomContent")` on `table.view(atColumn:row:makeIfNecessary:)`.
- Anything that needs a click, a key or the screen goes on the owner's list below.

## 10. Known limits and owner checks

They are open items: [status.md](status.md).
