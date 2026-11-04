import Foundation
import PRLoopKit
import Testing

@Suite struct MenuItemsTests {
    private func renumbered(_ items: [JSONValue]) -> [JSONValue] {
        (items + items).enumerated().map { index, item in
            guard case .object(var object) = item else { return item }
            object["number"] = .number(Double(index + 1))
            return .object(object)
        }
    }

    private func rows(_ items: MenuItems) -> [MenuItems.Row] {
        guard case .top(let rows) = items else { return [] }
        return rows
    }

    @Test("the top 5 items across every project, in the daemon's order")
    func top() throws {
        let rows = rows(.top(5, in: .live(try Snapshots.queue(items: renumbered))))
        #expect(rows.map(\.ref.number) == [1, 2, 3, 4, 5])
        #expect(Set(rows.map(\.ref.repo)) == ["iprally/iprally", "iprally/gitops"])
    }

    @Test("a row reads symbol, project, number and the title cut to 44 characters")
    func row() throws {
        let rows = rows(.top(5, in: .live(try Snapshots.queue())))
        #expect(
            rows.map(\.text).prefix(3) == [
                "iprally #17190  feat(search): keep filters on back navigati…",
                "iprally #17201  fix(api): retry the export job once",
                "iprally #17166  refactor(ui): one sub per hop in the filters",
            ])
        #expect(rows.map(\.symbol) == ["eye", "clock", "checkmark.seal.fill", "minus.circle"])
        #expect(rows.last?.text == "gitops #412  chore: bump the search image")
    }

    @Test("an empty queue reads empty")
    func empty() throws {
        #expect(MenuItems.top(5, in: .live(try Snapshots.queue { _ in [] })) == .empty)
    }

    @Test("a lost daemon reads down, with or without a snapshot")
    func down() throws {
        let retryAt = Date(timeIntervalSince1970: 0)
        #expect(MenuItems.top(5, in: .down(APIError.down, retryAt: retryAt)) == .down)
        #expect(MenuItems.top(5, in: .stale(try Snapshots.queue(), APIError.down, retryAt: retryAt)) == .down)
    }

    @Test("before the first snapshot and on a newer API")
    func other() {
        #expect(MenuItems.top(5, in: .connecting) == .connecting)
        #expect(MenuItems.top(5, in: .incompatible(api: 2)) == .incompatible(api: 2))
    }
}
