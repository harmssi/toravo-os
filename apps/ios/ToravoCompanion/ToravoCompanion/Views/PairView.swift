import SwiftUI
import VisionKit

struct PairView: View {
    @EnvironmentObject var model: AppModel
    @State private var scanning = false
    @State private var linkText = ""
    @State private var showPaste = false
    @State private var noCamera = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack(spacing: 12) { LogoT(size: 44); Wordmark(size: 15) }.padding(.top, 30)
                Text("Your AI studio,\nin your pocket.").font(.system(size: 34, weight: .heavy)).tracking(-0.5).foregroundStyle(T.text)
                Text("Watch your render queue, send commands to your PC and get your finished Shorts on your phone. Directly from your own computer – no cloud, no account.")
                    .font(.system(size: 16)).foregroundStyle(T.text2)

                Panel {
                    VStack(alignment: .leading, spacing: 12) {
                        MicroLabel("Connect", color: T.violet)
                        step(1, "On your Toravo OS PC open Toravo Studio → Connect phone.")
                        step(2, "Scan the QR code. Your phone and PC need to be in the same network.")
                        step(3, "Done. You can remove this phone in the Studio at any time.")
                    }
                }

                if model.link == .connecting {
                    HStack(spacing: 10) { ProgressView().tint(T.violet); Text("Connecting …").foregroundStyle(T.text2) }
                }
                if let e = model.lastError { Text(e).font(.system(size: 14)).foregroundStyle(T.coral) }

                PrimaryButton(title: String(localized: "Scan QR code"), id: "scanButton") {
                    if DataScannerViewController.isSupported && DataScannerViewController.isAvailable { scanning = true }
                    else { noCamera = true; showPaste = true }   // simulator / no camera permission: be honest, paste the link
                }
                if noCamera {
                    Text("No camera available here – paste the pairing link from Toravo Studio instead.")
                        .font(.system(size: 13)).foregroundStyle(T.coral)
                }
                Button { showPaste.toggle() } label: {
                    Text("Paste pairing link instead").font(.system(size: 15, weight: .semibold)).foregroundStyle(T.cyan)
                }
                if showPaste {
                    VStack(alignment: .leading, spacing: 10) {
                        TextField("", text: $linkText, prompt: Text("toravo://pair?…").foregroundStyle(T.text3), axis: .vertical)
                            .font(.system(size: 14, design: .monospaced)).foregroundStyle(T.text).lineLimit(1...4)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("pairField")
                            .padding(12).background(T.bg2, in: RoundedRectangle(cornerRadius: 10))
                            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(T.line))
                        HStack(spacing: 10) {
                            Button {
                                if let s = UIPasteboard.general.string { linkText = s }
                            } label: { Label("Paste", systemImage: "doc.on.clipboard").font(.system(size: 14, weight: .semibold)) }
                            Spacer()
                            Button { submit(linkText) } label: { Text("Connect").font(.system(size: 15, weight: .bold)) }
                                .disabled(PairLink(linkText) == nil).accessibilityIdentifier("connectButton")
                        }
                    }
                }
                Text("Local network only. The app checks your PC's key from the QR code before it sends anything.")
                    .font(.system(size: 12)).foregroundStyle(T.text3).padding(.top, 8)
            }.padding(22)
        }
        .sheet(isPresented: $scanning) {
            QRScanner { code in
                scanning = false
                submit(code)
            }.ignoresSafeArea()
        }
    }

    func step(_ n: Int, _ text: LocalizedStringKey) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text("\(n)").font(.system(size: 13, weight: .bold, design: .monospaced)).foregroundStyle(T.violet).frame(width: 16)
            Text(text).font(.system(size: 15)).foregroundStyle(T.text)
        }
    }

    func submit(_ s: String) {
        guard let l = PairLink(s) else {
            model.lastError = String(localized: "That is not a Toravo pairing code.")
            return
        }
        Task { await model.pair(with: l) }
    }
}

/// VisionKit QR scanner (real devices only – the simulator has no camera).
struct QRScanner: UIViewControllerRepresentable {
    let found: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let vc = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])], qualityLevel: .balanced,
                                           isHighlightingEnabled: true)
        vc.delegate = context.coordinator
        try? vc.startScanning()
        return vc
    }

    func updateUIViewController(_ vc: DataScannerViewController, context: Context) {}
    func makeCoordinator() -> Coord { Coord(found: found) }

    final class Coord: NSObject, DataScannerViewControllerDelegate {
        let found: (String) -> Void
        var done = false
        init(found: @escaping (String) -> Void) { self.found = found }
        func dataScanner(_ s: DataScannerViewController, didAdd items: [RecognizedItem], allItems: [RecognizedItem]) {
            for case let .barcode(b) in items {
                if let v = b.payloadStringValue, PairLink(v) != nil, !done {
                    done = true
                    s.stopScanning()
                    found(v)
                }
            }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var confirm = false

    var body: some View {
        List {
            Section {
                row("Computer", model.server?.name ?? model.pairing?.name ?? "–")
                row("Address", model.pairing.map { "\($0.hosts.first ?? "–"):\($0.port)" } ?? "–")
                row("Toravo OS", model.server?.version ?? "–")
                row("Key", model.pairing.map { String($0.fingerprint.prefix(16)) + "…" } ?? "–")
            } header: { Text("Paired computer") }
            Section {
                Text("While the app is open you get a notice as soon as a job is done. In the background iOS decides when the app may check (Background App Refresh) – that can take a while. Instant push would need an Apple push server, and Toravo does not run servers for you.")
                    .font(.system(size: 13)).foregroundStyle(T.text2)
                Button("Allow notifications") { Task { await model.requestNotifications() } }
            } header: { Text("Notifications") }
            Section {
                Button("Unpair this phone", role: .destructive) { confirm = true }
            } footer: { Text("Removes the token from this phone and from your computer.") }
        }
        .scrollContentBackground(.hidden)
        .background(T.bg)
        .navigationTitle(Text("Computer"))
        .confirmationDialog(Text("Unpair this phone?"), isPresented: $confirm, titleVisibility: .visible) {
            Button("Unpair", role: .destructive) { Task { await model.unpair(); dismiss() } }
        }
    }

    func row(_ k: LocalizedStringKey, _ v: String) -> some View {
        HStack { Text(k).foregroundStyle(T.text2); Spacer(); Text(v).font(.system(size: 13, design: .monospaced)).foregroundStyle(T.text).lineLimit(1) }
    }
}
