import Foundation
import Security

enum APIError: LocalizedError {
    case unreachable
    case pinMismatch
    case unauthorized
    case rateLimited
    case server(String, String?)
    case decode

    var errorDescription: String? {
        switch self {
        case .unreachable: return String(localized: "Your computer is not reachable. Are you in the same Wi-Fi?")
        case .pinMismatch: return String(localized: "The computer answered with a different key than the one in the QR code. Connection refused.")
        case .unauthorized: return String(localized: "This phone is no longer paired. Pair it again in Toravo Studio.")
        case .rateLimited: return String(localized: "Too many requests – please wait a moment.")
        case .server(let code, let msg): return msg ?? code
        case .decode: return String(localized: "Unexpected answer from the computer.")
        }
    }
}

/// Accepts exactly one server key: the one whose SPKI SHA-256 came with the QR code. Host name and CA are irrelevant
/// (the certificate is self-signed by the PC); the key is what we trust.
final class PinningDelegate: NSObject, URLSessionDelegate, URLSessionTaskDelegate {
    let fingerprint: String
    private(set) var lastMismatch = false

    init(fingerprint: String) { self.fingerprint = fingerprint }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate], let leaf = chain.first,
              let key = SecCertificateCopyKey(leaf),
              let raw = SecKeyCopyExternalRepresentation(key, nil) as Data?,
              let fp = Pin.fingerprint(rawP256: raw) else {
            lastMismatch = true
            return completionHandler(.cancelAuthenticationChallenge, nil)
        }
        if Pin.same(fp, fingerprint) {
            lastMismatch = false
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            lastMismatch = true
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
    }
}

final class APIClient {
    let host: String
    let port: Int
    let fingerprint: String
    var token: String?
    private let delegate: PinningDelegate
    private let session: URLSession
    private let downloads: URLSession

    init(host: String, port: Int, fingerprint: String, token: String?) {
        self.host = host
        self.port = port
        self.fingerprint = fingerprint
        self.token = token
        delegate = PinningDelegate(fingerprint: fingerprint)
        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 6
        cfg.waitsForConnectivity = false
        cfg.requestCachePolicy = .reloadIgnoringLocalCacheData
        session = URLSession(configuration: cfg, delegate: delegate, delegateQueue: nil)
        let dcfg = URLSessionConfiguration.ephemeral
        dcfg.timeoutIntervalForRequest = 30
        dcfg.timeoutIntervalForResource = 60 * 30
        downloads = URLSession(configuration: dcfg, delegate: delegate, delegateQueue: nil)
    }

    deinit {
        session.invalidateAndCancel()
        downloads.invalidateAndCancel()
    }

    var base: String {
        let h = host.contains(":") && !host.hasPrefix("[") ? "[\(host)]" : host
        return "https://\(h):\(port)"
    }

    func url(_ path: String) -> URL? { URL(string: base + path) }

    private func request(_ path: String, method: String = "GET", body: Encodable? = nil) throws -> URLRequest {
        guard let u = url(path) else { throw APIError.unreachable }
        var r = URLRequest(url: u)
        r.httpMethod = method
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        return r
    }

    func call<T: Decodable>(_ path: String, method: String = "GET", body: Encodable? = nil, as: T.Type = T.self) async throws -> T {
        let r = try request(path, method: method, body: body)
        let data: Data, resp: URLResponse
        do {
            (data, resp) = try await session.data(for: r)
        } catch {
            throw delegate.lastMismatch ? APIError.pinMismatch : APIError.unreachable
        }
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 { throw APIError.unauthorized }
        if code == 429 { throw APIError.rateLimited }
        guard (200..<300).contains(code) else {
            let e = try? JSONDecoder().decode(APIErrorBody.self, from: data)
            throw APIError.server(e?.error ?? "http \(code)", e?.message)
        }
        do { return try JSONDecoder().decode(T.self, from: data) } catch { throw APIError.decode }
    }

    // MARK: endpoints (docs/COMPANION.md)
    func hello() async throws -> Hello { try await call("/api/v1/hello") }
    func pair(code: String, device: String, model: String) async throws -> PairReply {
        try await call("/api/v1/pair", method: "POST", body: ["code": code, "device": device, "model": model])
    }
    func unpair() async throws { let _: [String: Bool] = try await call("/api/v1/unpair", method: "POST") }
    func status() async throws -> Status { try await call("/api/v1/status") }
    func events(since: Int64) async throws -> EventsReply { try await call("/api/v1/events?since=\(since)") }
    func plan(_ text: String) async throws -> Plan { try await call("/api/v1/plan", method: "POST", body: ["text": text]) }
    func run(planID: String) async throws -> RunReply {
        try await call("/api/v1/plans/\(planID.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "")/run", method: "POST")
    }
    func job(_ id: String, _ action: String) async throws -> JobReply {
        try await call("/api/v1/jobs/\(id.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "")/\(action)", method: "POST")
    }
    func media(kind: String = "all", limit: Int = 60) async throws -> [Media] {
        let r: MediaReply = try await call("/api/v1/media?kind=\(kind)&limit=\(limit)")
        return r.items
    }

    /// Small things (posters) in memory.
    func data(_ path: String) async throws -> Data {
        let r = try request(path)
        do {
            let (d, resp) = try await session.data(for: r)
            guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw APIError.server("http", nil) }
            return d
        } catch let e as APIError { throw e } catch { throw delegate.lastMismatch ? APIError.pinMismatch : APIError.unreachable }
    }

    /// Files to a local cache file (pinned session, Bearer header) – AVPlayer then plays the local copy.
    func download(_ m: Media) async throws -> URL {
        let dir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("media", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let safe = m.name.replacingOccurrences(of: "/", with: "_")
        let dst = dir.appendingPathComponent("\(Pin.sha256Hex(Data(m.id.utf8)).prefix(10))-\(safe)")
        if let a = try? FileManager.default.attributesOfItem(atPath: dst.path), let s = a[.size] as? Int64, s == (m.size ?? -1) { return dst }
        let r = try request(m.url)
        let tmp: URL, resp: URLResponse
        do { (tmp, resp) = try await downloads.download(for: r) } catch {
            throw delegate.lastMismatch ? APIError.pinMismatch : APIError.unreachable
        }
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw APIError.server("http", nil) }
        try? FileManager.default.removeItem(at: dst)
        try FileManager.default.moveItem(at: tmp, to: dst)
        return dst
    }
}

struct AnyEncodable: Encodable {
    let value: Encodable
    init(_ v: Encodable) { value = v }
    func encode(to encoder: Encoder) throws { try value.encode(to: encoder) }
}

/// The device token lives only in the Keychain (this device only, not in backups).
enum Keychain {
    static let service = "de.toravo.companion"

    static func set(_ value: String, for account: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
        SecItemDelete(q as CFDictionary)
        var add = q
        add[kSecValueData as String] = Data(value.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }

    static func get(_ account: String) -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account,
                                kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func delete(_ account: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
        SecItemDelete(q as CFDictionary)
    }
}
