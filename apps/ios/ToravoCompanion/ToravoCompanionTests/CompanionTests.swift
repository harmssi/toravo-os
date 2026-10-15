import XCTest
@testable import ToravoCompanion

final class PairLinkTests: XCTestCase {
    let fp = String(repeating: "ab", count: 32)

    func testParsesFullLink() {
        let l = PairLink("toravo://pair?v=1&h=192.168.1.20,10.0.0.5&p=8891&c=ABCDE-FGHJK&fp=\(fp)&id=srv1&n=Studio%20PC")
        XCTAssertEqual(l?.hosts, ["192.168.1.20", "10.0.0.5"])
        XCTAssertEqual(l?.port, 8891)
        XCTAssertEqual(l?.code, "ABCDEFGHJK")
        XCTAssertEqual(l?.fingerprint, fp)
        XCTAssertEqual(l?.serverID, "srv1")
        XCTAssertEqual(l?.name, "Studio PC")
    }

    func testRejectsBadLinks() {
        XCTAssertNil(PairLink("https://evil.example/pair?h=1.2.3.4&c=ABCDEFGHJK&fp=\(fp)"))       // wrong scheme
        XCTAssertNil(PairLink("toravo://pair?h=1.2.3.4&c=ABCDEFGHJK&fp=abc"))                      // short fingerprint
        XCTAssertNil(PairLink("toravo://pair?h=1.2.3.4&c=ABCDEFGHJ1&fp=\(fp)"))                    // '1' not in alphabet
        XCTAssertNil(PairLink("toravo://pair?h=1.2.3.4&c=ABC&fp=\(fp)"))                           // short code
        XCTAssertNil(PairLink("toravo://pair?h=a/b@c&c=ABCDEFGHJK&fp=\(fp)"))                      // host with path/userinfo
        XCTAssertNil(PairLink("toravo://pair?h=1.2.3.4&p=70000&c=ABCDEFGHJK&fp=\(fp)"))            // port out of range
        XCTAssertNil(PairLink("toravo://pair?c=ABCDEFGHJK&fp=\(fp)"))                              // no host
    }

    func testCodeNormalisation() {
        XCTAssertEqual(PairLink.normalize(code: "abcde fghjk"), "ABCDEFGHJK")
        XCTAssertNil(PairLink.normalize(code: "ABCDE-FGHJO"))  // O is ambiguous, not used
    }
}

final class PinTests: XCTestCase {
    func testSPKIFingerprintMatchesOpenSSL() {
        // EC P-256 public key, raw point 04||X||Y; expected = `openssl pkey -pubout -outform DER | sha256sum` of the same key.
        let raw = Data(hex: "04" + "6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296"
                       + "4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5")
        let fp = Pin.fingerprint(rawP256: raw)
        // (the P-256 generator point; openssl re-encodes our header+raw identically -> same SPKI bytes)
        XCTAssertEqual(fp, "5cd252fb0ce8932436faf8ccd1040981b89ee4ad6b9fe9e2a2b7e71aacb27cd3")
        XCTAssertNil(Pin.fingerprint(rawP256: raw.dropFirst()))
    }

    func testConstantTimeCompare() {
        XCTAssertTrue(Pin.same("ABcd", "abCD"))
        XCTAssertFalse(Pin.same("abcd", "abce"))
        XCTAssertFalse(Pin.same("abcd", "abc"))
    }
}

final class LayoutTests: XCTestCase {
    func testFoldedIsOneColumnUnfoldedIsTwo() {
        XCTAssertEqual(LayoutMode.forWidth(466), .single)   // iPhone Duo outer display (simulator: 1398 px @3x)
        XCTAssertEqual(LayoutMode.forWidth(402), .single)   // regular iPhone
        XCTAssertEqual(LayoutMode.forWidth(669), .split)    // iPhone Duo inner display (simulator: 2007 px @3x)
    }
}

final class DecodeTests: XCTestCase {
    func testStatusDecodes() throws {
        let json = """
        {"server":{"name":"Studio","id":"x","version":"0.1.7"},"gpu":{"name":"RTX","util":71,"vram_used":14.2,"vram_total":24,"temp":63},
         "jobs":[{"id":"j1","kind":"shorts","title":"Cut 3 Shorts","state":"running","progress":0.4,"step":"Short 2/3",
                  "outputs":[{"id":"c2hvcnRzL2EubXA0","kind":"shorts","name":"a.mp4","size":10,"mtime":1,"type":"video",
                              "url":"/api/v1/media/c2hvcnRzL2EubXA0","poster":"/api/v1/media/c2hvcnRzL2EubXA0/poster"}],
                  "can_pause":false,"can_resume":false,"can_cancel":true}],"events_seq":5,"time":1}
        """
        let s = try JSONDecoder().decode(Status.self, from: Data(json.utf8))
        XCTAssertEqual(s.jobs.first?.media.first?.isVideo, true)
        XCTAssertEqual(s.gpu.temp, 63)
        XCTAssertTrue(s.jobs[0].isActive)
    }
}

extension Data {
    init(hex: String) {
        var d = Data()
        var i = hex.startIndex
        while i < hex.endIndex {
            let j = hex.index(i, offsetBy: 2)
            d.append(UInt8(hex[i..<j], radix: 16)!)
            i = j
        }
        self = d
    }
}
