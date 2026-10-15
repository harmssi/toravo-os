import Foundation
import SwiftUI
import UserNotifications
import BackgroundTasks

@MainActor
final class AppModel: ObservableObject {
    enum Link { case unpaired, connecting, online, offline, revoked }

    @Published var pairing: Pairing?
    @Published var link: Link = .unpaired
    @Published var server: ServerInfo?
    @Published var gpu: GPU = .empty
    @Published var jobs: [Job] = []
    @Published var media: [Media] = []
    @Published var lastError: String?
    @Published var selectedJobID: String?
    @Published var spotlight: Media?          // newest finished output (shown in the preview pane / as banner)
    @Published var banner: String?

    // Command Bar
    @Published var command = ""
    @Published var plan: Plan?
    @Published var planning = false
    @Published var starting = false

    private(set) var client: APIClient?
    private var loop: Task<Void, Never>?
    private var tick = 0
    static let refreshTask = "de.toravo.companion.refresh"

    private var eventSeq: Int64 {
        get { Int64(UserDefaults.standard.string(forKey: "eventSeq") ?? "") ?? -1 }
        set { UserDefaults.standard.set(String(newValue), forKey: "eventSeq") }
    }

    init() {
        if let d = UserDefaults.standard.data(forKey: "pairing"), let p = try? JSONDecoder().decode(Pairing.self, from: d),
           let token = Keychain.get(p.deviceID) {
            pairing = p
            client = APIClient(host: p.hosts.first ?? "", port: p.port, fingerprint: p.fingerprint, token: token)
            link = .connecting
        }
    }

    var activeJobs: [Job] { jobs.filter { $0.isActive } }
    var finishedJobs: [Job] { jobs.filter { !$0.isActive }.sorted { ($0.finished ?? 0) > ($1.finished ?? 0) } }
    var selectedJob: Job? { jobs.first { $0.id == selectedJobID } }

    // MARK: pairing
    func pair(with link: PairLink) async {
        lastError = nil
        self.link = .connecting
        var lastErr: Error = APIError.unreachable
        for host in link.hosts {
            let c = APIClient(host: host, port: link.port, fingerprint: link.fingerprint, token: nil)
            do {
                let hello = try await c.hello()
                let reply = try await c.pair(code: link.code, device: Device.kind, model: Device.model)
                let p = Pairing(serverID: hello.id, name: reply.server.name, hosts: [host] + link.hosts.filter { $0 != host },
                                port: link.port, fingerprint: link.fingerprint, deviceID: reply.device_id)
                Keychain.set(reply.token, for: p.deviceID)
                c.token = reply.token
                save(p)
                client = c
                server = reply.server
                self.link = .online
                eventSeq = -1
                await refresh()
                await requestNotifications()
                return
            } catch { lastErr = error }
        }
        lastError = (lastErr as? LocalizedError)?.errorDescription ?? lastErr.localizedDescription
        self.link = pairing == nil ? .unpaired : .offline
    }

    func unpair() async {
        if link == .online { try? await client?.unpair() }
        forget()
    }

    func forget() {
        if let p = pairing { Keychain.delete(p.deviceID) }
        UserDefaults.standard.removeObject(forKey: "pairing")
        pairing = nil
        client = nil
        jobs = []
        media = []
        spotlight = nil
        plan = nil
        link = .unpaired
    }

    private func save(_ p: Pairing) {
        pairing = p
        if let d = try? JSONEncoder().encode(p) { UserDefaults.standard.set(d, forKey: "pairing") }
    }

    // MARK: live loop (only while the app is active)
    func start() {
        guard loop == nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.refresh()
                let fast = self.jobs.contains { $0.state == "running" }
                try? await Task.sleep(nanoseconds: fast ? 1_200_000_000 : 3_000_000_000)
            }
        }
    }

    func stop() {
        loop?.cancel()
        loop = nil
        scheduleBackgroundRefresh()
    }

    func refresh() async {
        guard let c = client, pairing != nil else { return }
        do {
            let s = try await c.status()
            server = s.server
            gpu = s.gpu
            withAnimation(.easeOut(duration: 0.25)) { jobs = s.jobs.sorted { ($0.created ?? 0) > ($1.created ?? 0) } }
            link = .online
            lastError = nil
            if eventSeq < 0 { eventSeq = s.events_seq ?? 0 } else { await pollEvents(c) }
            if tick % 5 == 0 || media.isEmpty { media = (try? await c.media()) ?? media }
            tick += 1
        } catch APIError.unauthorized {
            link = .revoked
        } catch {
            link = .offline
            lastError = (error as? LocalizedError)?.errorDescription
            await relocate()
        }
    }

    private func pollEvents(_ c: APIClient) async {
        guard let r = try? await c.events(since: eventSeq) else { return }
        for e in r.events where e.seq > eventSeq { await handle(e) }
        eventSeq = max(eventSeq, r.seq)
    }

    private func handle(_ e: Event) async {
        switch e.type {
        case "done":
            let outs = e.outputs ?? []
            if let first = outs.first(where: { $0.isVideo }) ?? outs.first {
                withAnimation(.spring(duration: 0.4)) { spotlight = first }
                media = (try? await client?.media()) ?? media
            }
            banner = String(localized: "Done: \(e.title)")
            Notify.post(title: String(localized: "Done: \(e.title)"), body: outs.prefix(3).map(\.name).joined(separator: ", "), id: "\(e.seq)")
        case "failed", "needs_tool":
            banner = String(localized: "Problem: \(e.title)")
            Notify.post(title: String(localized: "Problem: \(e.title)"), body: String(localized: "Open Toravo to see what happened."), id: "\(e.seq)")
        default: break
        }
    }

    /// The PC got a new address? Ask Bonjour for the same server id + key.
    private var lastLocate = Date.distantPast
    private func relocate() async {
        guard let p = pairing, Date().timeIntervalSince(lastLocate) > 20 else { return }
        lastLocate = Date()
        guard let f = await Discovery.locate(p), f.host != client?.host else { return }
        var np = p
        np.hosts = [f.host] + p.hosts.filter { $0 != f.host }
        np.port = f.port
        save(np)
        client = APIClient(host: f.host, port: f.port, fingerprint: p.fingerprint, token: Keychain.get(p.deviceID))
    }

    // MARK: Command Bar
    func makePlan() async {
        let text = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let c = client else { return }
        planning = true
        defer { planning = false }
        do { withAnimation { plan = nil }; let p = try await c.plan(text); withAnimation(.spring(duration: 0.35)) { plan = p } }
        catch { lastError = (error as? LocalizedError)?.errorDescription }
    }

    func runPlan() async {
        guard let p = plan, let c = client else { return }
        starting = true
        defer { starting = false }
        do {
            let r = try await c.run(planID: p.plan_id)
            withAnimation { plan = nil; command = "" }
            selectedJobID = r.jobs.first
            await refresh()
        } catch { lastError = (error as? LocalizedError)?.errorDescription }
    }

    func act(_ job: Job, _ action: String) async {
        guard let c = client else { return }
        do { _ = try await c.job(job.id, action); await refresh() }
        catch { lastError = (error as? LocalizedError)?.errorDescription }
    }

    // MARK: notifications
    func requestNotifications() async {
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
    }

    func scheduleBackgroundRefresh() {
        guard pairing != nil else { return }
        let r = BGAppRefreshTaskRequest(identifier: Self.refreshTask)
        r.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        Task { try? await BGTaskScheduler.shared.submitTaskRequest(r) }
    }

    /// Background App Refresh: iOS decides when (best effort). One status + events round trip, then notifications.
    func backgroundRefresh() async {
        scheduleBackgroundRefresh()
        guard let c = client, eventSeq >= 0 else { return }
        await pollEvents(c)
    }
}

enum Notify {
    static func post(title: String, body: String, id: String) {
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = body
        c.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "toravo-\(id)", content: c, trigger: nil))
    }
}

enum Device {
    static var kind: String { "iPhone" }
    static var model: String {
        var u = utsname()
        uname(&u)
        let m = withUnsafeBytes(of: &u.machine) { String(decoding: $0.prefix { $0 != 0 }, as: UTF8.self) }
        if m.hasPrefix("arm64") || m.hasPrefix("x86"), let sim = ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] { return sim }
        return m
    }
}
