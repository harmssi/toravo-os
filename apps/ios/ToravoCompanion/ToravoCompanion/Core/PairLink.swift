import Foundation
import CryptoKit

/// toravo://pair?v=1&h=<ip>[,<ip>]&p=8891&c=<code>&fp=<sha256 hex>&id=<server id>&n=<pc name>   (docs/COMPANION.md)
struct PairLink: Equatable {
    var hosts: [String]
    var port: Int
    var code: String
    var fingerprint: String
    var serverID: String
    var name: String

    static let codeAlphabet = Set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")

    init?(_ text: String) {
        guard let c = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              c.scheme?.lowercased() == "toravo", (c.host ?? c.path).lowercased().hasPrefix("pair") else { return nil }
        var q: [String: String] = [:]
        for item in c.queryItems ?? [] { q[item.name] = item.value ?? "" }
        guard let code = PairLink.normalize(code: q["c"] ?? ""),
              let fp = q["fp"]?.lowercased(), fp.count == 64, fp.allSatisfy({ $0.isHexDigit }),
              let h = q["h"], !h.isEmpty else { return nil }
        let hosts = h.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }.filter(PairLink.isPlausibleHost)
        guard !hosts.isEmpty else { return nil }
        self.hosts = hosts
        self.port = Int(q["p"] ?? "") ?? 8891
        guard (1...65535).contains(port) else { return nil }
        self.code = code
        self.fingerprint = fp
        self.serverID = q["id"] ?? ""
        self.name = (q["n"]?.isEmpty == false ? q["n"]! : "Toravo OS")
    }

    /// "abcde-fghjk" / "ABCDE FGHJK" -> "ABCDEFGHJK"; nil if it cannot be a pairing code.
    static func normalize(code: String) -> String? {
        let c = code.uppercased().filter { !$0.isWhitespace && $0 != "-" }
        guard c.count == 10, c.allSatisfy({ codeAlphabet.contains($0) }) else { return nil }
        return c
    }

    /// Only plain IPs or local host names – never a URL with path, user info or spaces.
    static func isPlausibleHost(_ h: String) -> Bool {
        guard !h.isEmpty, h.count <= 253 else { return false }
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:%")
        return h.unicodeScalars.allSatisfy { allowed.contains($0) }
    }
}

enum Pin {
    /// DER prefix of a SubjectPublicKeyInfo for an uncompressed EC P-256 key (id-ecPublicKey, prime256v1).
    static let spkiP256Header: [UInt8] = [0x30, 0x59, 0x30, 0x13, 0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01,
                                          0x06, 0x08, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07, 0x03, 0x42, 0x00]

    static func sha256Hex(_ d: Data) -> String {
        SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined()
    }

    /// Fingerprint as the PC prints it: sha256 over SPKI DER. `raw` = SecKeyCopyExternalRepresentation (04 || X || Y).
    static func fingerprint(rawP256 raw: Data) -> String? {
        guard raw.count == 65, raw.first == 0x04 else { return nil }
        return sha256Hex(Data(spkiP256Header) + raw)
    }

    /// Constant-time comparison of two hex fingerprints.
    static func same(_ a: String, _ b: String) -> Bool {
        let x = Array(a.lowercased().utf8), y = Array(b.lowercased().utf8)
        guard x.count == y.count else { return false }
        var diff: UInt8 = 0
        for i in 0..<x.count { diff |= x[i] ^ y[i] }
        return diff == 0
    }
}
