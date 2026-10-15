import Foundation
import Network

/// Finds Toravo OS computers in the local network (Bonjour `_toravo._tcp`, TXT: v, id, fp). Used when the paired PC got a
/// new IP address: we look for the same server id and key fingerprint prefix and resolve its current address.
final class Discovery {
    struct Found: Equatable { var name: String; var id: String; var fpPrefix: String; var host: String; var port: Int }

    /// Browses for `seconds` and returns all servers that could be resolved.
    static func browse(seconds: Double = 4) async -> [Found] {
        await withCheckedContinuation { (cont: CheckedContinuation<[Found], Never>) in
            let q = DispatchQueue(label: "toravo.discovery")
            let browser = NWBrowser(for: .bonjourWithTXTRecord(type: "_toravo._tcp", domain: nil), using: .tcp)
            let st = State()   // only touched on queue q (browser, connections and the timer all run there)
            browser.browseResultsChangedHandler = { results, _ in
                for r in results {
                    guard case let .service(name, _, _, _) = r.endpoint else { continue }
                    let txt: [String: String]
                    if case let .bonjour(record) = r.metadata { txt = record.dictionary } else { txt = [:] }
                    let c = NWConnection(to: r.endpoint, using: .tcp)
                    st.pending.append(c)
                    c.stateUpdateHandler = { cs in
                        if case .ready = cs, case let .hostPort(host, port)? = c.currentPath?.remoteEndpoint {
                            var h = "\(host)"
                            if let pct = h.firstIndex(of: "%"), !h.hasPrefix("fe80") { h = String(h[..<pct]) }
                            let f = Found(name: name, id: txt["id"] ?? "", fpPrefix: (txt["fp"] ?? "").lowercased(), host: h, port: Int(port.rawValue))
                            if !st.found.contains(f) { st.found.append(f) }
                            c.cancel()
                        }
                    }
                    c.start(queue: q)
                }
            }
            browser.start(queue: q)
            q.asyncAfter(deadline: .now() + seconds) {
                guard !st.done else { return }
                st.done = true
                browser.cancel()
                st.pending.forEach { $0.cancel() }
                cont.resume(returning: st.found)
            }
        }
    }

    private final class State: @unchecked Sendable { var found: [Found] = []; var pending: [NWConnection] = []; var done = false }

    /// The paired server's current address, if it announces itself.
    static func locate(_ p: Pairing) async -> Found? {
        let all = await browse()
        return all.first { $0.id == p.serverID && !$0.fpPrefix.isEmpty && p.fingerprint.hasPrefix($0.fpPrefix) }
    }
}
