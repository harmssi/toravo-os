import XCTest

/// Real UI flows against a real Toravo OS PC (no mocks). Used for smoke tests and for the screen recordings of the
/// episode: `TEST_RUNNER_PAIR_LINK=… TEST_RUNNER_DEMO_CMD=… xcodebuild test -scheme Demo …` (variables reach the runner without
/// the prefix). Every test skips itself when its variable is missing, so a plain test run never needs a PC.
final class DemoUITests: XCTestCase {
    let env = ProcessInfo.processInfo.environment

    override func setUp() { continueAfterFailure = false }

    func app() -> XCUIApplication {
        let a = XCUIApplication()
        a.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US", "-TORAVO_MUTE", "YES"]
        return a
    }

    func el(_ a: XCUIApplication, _ id: String) -> XCUIElement { a.descendants(matching: .any)[id].firstMatch }
    func pause(_ s: Double) { Thread.sleep(forTimeInterval: s) }
    func wait(_ name: String) -> Double { Double(env[name] ?? "") ?? 0 }

    func slowType(_ e: XCUIElement, _ text: String, delay: useconds_t = 55_000) {
        for c in text { e.typeText(String(c)); usleep(delay) }
    }

    func allowSystemAlert() {
        let sb = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for label in ["Allow", "OK", "Allow Full Access"] where sb.buttons[label].waitForExistence(timeout: 1.5) {
            sb.buttons[label].tap()
            return
        }
    }

    /// Pairing by pasting the link (the simulator has no camera): Scan → honest "no camera" hint → link → Connect.
    func testDemo1Pair() throws {
        guard let link = env["PAIR_LINK"] else { throw XCTSkip("PAIR_LINK not set") }
        let a = app()
        a.launch()
        pause(wait("LEAD") > 0 ? wait("LEAD") : 3)
        el(a, "scanButton").tap()
        pause(2.5)
        let f = el(a, "pairField")
        f.tap()
        pause(0.6)
        f.typeText(link)
        pause(1.2)
        el(a, "connectButton").tap()
        pause(2)
        allowSystemAlert()
        XCTAssertTrue(a.staticTexts["RENDER QUEUE"].waitForExistence(timeout: 30))
        pause(5)
    }

    /// One Command Bar sentence → plan → start on the PC → wait until the first result lands on the phone → play → save.
    func testDemo2Command() throws {
        guard let cmd = env["DEMO_CMD"] else { throw XCTSkip("DEMO_CMD not set") }
        let a = app()
        a.launch()
        pause(3)
        let f = el(a, "commandField")
        f.tap()
        pause(0.5)
        slowType(f, cmd)
        pause(1)
        el(a, "planButton").tap()
        XCTAssertTrue(el(a, "startButton").waitForExistence(timeout: 300))
        pause(4)
        el(a, "startButton").tap()
        pause(4)
        if env["DEMO_PAUSE"] != nil {   // long-press a waiting job → Pause, then Resume
            let q = a.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'job-' AND identifier ENDSWITH '-queued'")).firstMatch
            if q.waitForExistence(timeout: 10) {
                q.press(forDuration: 1.0)
                if a.buttons["Pause"].waitForExistence(timeout: 3) { a.buttons["Pause"].tap() }
                pause(3)
                let p = a.descendants(matching: .any).matching(NSPredicate(format: "identifier ENDSWITH '-paused'")).firstMatch
                if p.waitForExistence(timeout: 8) {
                    p.press(forDuration: 1.0)
                    if a.buttons["Resume"].waitForExistence(timeout: 3) { a.buttons["Resume"].tap() }
                }
                pause(3)
            }
        }
        let total = wait("DEMO_WAIT") > 0 ? wait("DEMO_WAIT") : 1800
        let doneKind = env["DEMO_DONE_KIND"] ?? "shorts"   // wait for this job (the music video finishes first, the Shorts last)
        XCTAssertTrue(a.descendants(matching: .any).matching(NSPredicate(format: "identifier == %@", "job-\(doneKind)-done")).firstMatch
            .waitForExistence(timeout: total))
        XCTAssertTrue(a.staticTexts["JUST FINISHED"].waitForExistence(timeout: 30))
        pause(3)
        let m = a.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'media-'")).firstMatch
        m.tap()
        pause(9)
        if el(a, "saveButton").exists { el(a, "saveButton").tap(); pause(1); allowSystemAlert() }
        pause(4)
    }

    /// Browse: tap the newest finished job (unfolded: it opens in the right column), play its first result.
    func testDemo3Browse() throws {
        guard env["DEMO_BROWSE"] != nil else { throw XCTSkip("DEMO_BROWSE not set") }
        let a = app()
        a.launch()
        pause(4)
        let j = a.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'job-shorts-done'")).firstMatch
        if j.waitForExistence(timeout: 10) { j.tap() }
        pause(3)
        let m = a.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH 'media-'")).firstMatch
        if m.waitForExistence(timeout: 10) { m.tap() }
        pause(wait("HOLD") > 0 ? wait("HOLD") : 12)
    }
}
