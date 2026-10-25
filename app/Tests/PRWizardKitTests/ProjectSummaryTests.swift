import PRWizardKit
import Testing

@Suite struct ProjectSummaryTests {
    private func summaries(_ snapshot: QueueSnapshot) -> [String: ProjectSummary] {
        Dictionary(uniqueKeysWithValues: snapshot.projects.map { ($0.repo, ProjectSummary($0, in: snapshot)) })
    }

    @Test("counts ready and active items per project")
    func counts() throws {
        let projects = summaries(try Snapshots.queue())
        let iprally = try #require(projects["iprally/iprally"])
        let gitops = try #require(projects["iprally/gitops"])
        #expect((iprally.name, iprally.readyCount, iprally.activeCount) == ("iprally", 1, 1))
        #expect((gitops.name, gitops.readyCount, gitops.activeCount) == ("gitops", 0, 0))
    }

    @Test("keeps status, availability and the effective lanes")
    func status() throws {
        let projects = summaries(try Snapshots.queue())
        let gitops = try #require(projects["iprally/gitops"]?.project)
        let site = try #require(projects["clojure/clojurescript-site"]?.project)
        #expect((gitops.status, gitops.isReviewEnabled, gitops.isFixEnabled) == (.active, false, true))
        #expect((site.status, site.isAvailable) == (.noCheckout, false))
    }

    @Test("shared lanes give no project its own pools")
    func sharedPools() throws {
        #expect(summaries(try Snapshots.queue()).values.allSatisfy { $0.pools.isEmpty })
    }

    @Test("separate lanes give each project its own pools")
    func separatePools() throws {
        let lanes: JSONValue = .object([
            "separate": .bool(true),
            "pools": .array([
                Snapshots.pool("review", "iprally/iprally", busy: 1), Snapshots.pool("fix", "iprally/iprally"),
                Snapshots.pool("fix", "iprally/gitops"),
            ]),
        ])
        let projects = summaries(try Snapshots.queue(lanes: lanes))
        #expect(projects["iprally/iprally"]?.pools.map(\.id) == ["review:iprally/iprally", "fix:iprally/iprally"])
        #expect(projects["iprally/gitops"]?.pools.map(\.id) == ["fix:iprally/gitops"])
        #expect(projects["sandudorogan/dataspex"]?.pools == [])
    }

    @Test("the lane line names the lanes or why none run")
    func laneLine() throws {
        let projects = summaries(try Snapshots.queue())
        #expect(projects["iprally/iprally"]?.laneLine == "review · fix")
        #expect(projects["iprally/gitops"]?.laneLine == "fix only")
        #expect(projects["clojure/clojurescript-site"]?.laneLine == "no local checkout")
        #expect(projects["clojure/clojurescript-site"]?.needsAttention == true)
        #expect(projects["iprally/iprally"]?.needsAttention == false)
    }

    @Test(
        "every status and lane switch reads as one line",
        arguments: [
            ("active", true, false, "review only"),
            ("off", false, false, "lanes off"),
            ("error", true, true, "checkout error"),
        ])
    func laneLines(status: String, review: Bool, fix: Bool, line: String) throws {
        let project = try Snapshots.project(0, ["status": .string(status), "review": .bool(review), "fix": .bool(fix)])
        #expect(ProjectSummary(project, in: try Snapshots.queue()).laneLine == line)
    }
}
