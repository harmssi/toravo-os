# Toravo Companion – App Store / TestFlight checklist

Nothing of this is done automatically. Signing, TestFlight and App Store submission are done by the account owner by hand.
No team ids, certificates or provisioning profiles belong into this repository.

## Identity
- Bundle id (proposal): `de.toravo.companion` (tests: `de.toravo.companion.tests`)
- Display name: **Toravo** · App Store name (proposal): **Toravo Companion for Toravo OS**
- Category: Productivity (secondary: Photo & Video)
- Minimum iOS: 27.0 · iPhone only · portrait
- Version 0.1.0 (1)

## Build
1. `brew install xcodegen` and `xcodegen generate` in `apps/ios/ToravoCompanion`
2. Open `ToravoCompanion.xcodeproj`, set your own team under Signing & Capabilities (locally, do not commit)
3. Capabilities in use: Background Modes → Background fetch. No push, no iCloud, no App Groups.
4. Product → Archive → Distribute → TestFlight (internal testers first)

## App Privacy (App Store Connect → App Privacy)
- **Data collection: none.** The app sends nothing to the developer or to third parties. It only talks to the user's own
  Toravo OS computer in the local network.
- No tracking, no analytics, no ads, no third-party SDKs.
- Stored on the device only: pairing data (computer name, address, key fingerprint) in UserDefaults, the device token in the
  Keychain (this device only), downloaded media in Caches.
- Privacy policy URL: required – page on toravo.de still to be written (state the above).

## Permission texts (Info.plist, EN + DE)
- Local network (`NSLocalNetworkUsageDescription`, Bonjour `_toravo._tcp`)
- Camera (`NSCameraUsageDescription`) – only for the pairing QR code
- Photos, add only (`NSPhotoLibraryAddUsageDescription`) – "Save" for finished Shorts/thumbnails

## Export compliance
- `ITSAppUsesNonExemptEncryption = NO`: only Apple's system TLS/CryptoKit for HTTPS + SHA-256 pinning (exempt standard
  encryption). Confirm in App Store Connect.

## App Review notes (important)
The app needs a Toravo OS computer to do anything. Reviewers do not have one. Prepare before submitting:
- A demo video of pairing + a job (the recordings from content/ep02 work), and/or
- A reachable demo setup is NOT possible (local network only by design) – say so in the review notes and explain the
  pairing flow; offer a video call. Expect questions under guideline 2.1 (app completeness) and 4.2 (minimum functionality).

## Screenshots
- iPhone Duo: both displays (outer 1398 × 2034 px, inner 2007 × 2853 px in the Xcode 27.1 simulator) – required by Apple
  from April 2027 for apps that run on iPhone Duo; take them with `xcrun simctl io <device> screenshot --display=1|3`.
- 6.9" iPhone (1320 × 2868) as usual.
- English + German UI (simulator language).
- No Apple device frames or logos in marketing material.

## Before the first public build
- [ ] Privacy policy page on toravo.de
- [ ] Support URL (GitHub issues or toravo.de/os)
- [ ] Test on a real iPhone (pairing via camera, local-network permission prompt, Photos save, Background App Refresh)
- [ ] Test with a real Toravo OS PC on Wi-Fi (Bonjour re-discovery after an IP change)
- [ ] Owner OK
