import SwiftUI

struct RootView: View {
    @EnvironmentObject var model: AppModel
    @State private var hinge = HingeState.unknown

    var body: some View {
        GeometryReader { g in
            let mode = LayoutMode.forWidth(g.size.width)
            ZStack {
                T.bg.ignoresSafeArea()
                Glow()
                if model.pairing == nil {
                    PairView()
                } else if mode == .split {
                    SplitLayout(hinge: hinge)
                } else {
                    CompactLayout()
                }
            }
            .animation(.spring(duration: 0.45), value: mode)
        }
        .modifier(HingeObserver(state: $hinge))
        .overlay(alignment: .top) { BannerView() }
        .task { model.start() }
    }
}

enum HingeState: Equatable { case unknown, closed, partiallyOpen, fullyOpen }

/// iPhone Duo: SwiftUI hinge updates (iOS 27.1+). Other iPhones simply never call it.
struct HingeObserver: ViewModifier {
    @Binding var state: HingeState
    func body(content: Content) -> some View {
        if #available(iOS 27.1, *) {
            content.onHingeChange { _, new in
                guard let h = new.hinge else { state = .unknown; return }
                switch h.status {
                case .closed: state = .closed
                case .partiallyOpen: state = .partiallyOpen
                case .fullyOpen: state = .fullyOpen
                default: state = .unknown
                }
            }
        } else {
            content
        }
    }
}

struct BannerView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        if let b = model.banner {
            HStack(spacing: 10) {
                Circle().fill(T.green).frame(width: 8, height: 8)
                Text(b).font(.system(size: 14, weight: .semibold)).foregroundStyle(T.text).lineLimit(2)
            }
            .padding(.horizontal, 16).padding(.vertical, 11)
            .background(T.panel2, in: Capsule()).overlay(Capsule().strokeBorder(T.line))
            .shadow(color: .black.opacity(0.5), radius: 14, y: 6)
            .padding(.top, 6)
            .transition(.move(edge: .top).combined(with: .opacity))
            .task(id: b) {
                try? await Task.sleep(nanoseconds: 4_000_000_000)
                withAnimation { model.banner = nil }
            }
        }
    }
}

// MARK: folded – one column with tabs
struct CompactLayout: View {
    @EnvironmentObject var model: AppModel
    @State private var tab = 0

    var body: some View {
        TabView(selection: $tab) {
            NavigationStack {
                ScrollView {
                    VStack(spacing: 14) {
                        Header()
                        GPUCard()
                        CommandBar()
                        if let s = model.spotlight { SpotlightCard(media: s) }
                        QueueList(navigates: true)
                    }.padding(.horizontal, 16).padding(.bottom, 24)
                }
                .scrollContentBackground(.hidden)
                .background { ZStack { T.bg; Glow() }.ignoresSafeArea() }
                .refreshable { await model.refresh() }
                .navigationDestination(for: String.self) { id in JobDetail(jobID: id) }
                .toolbar(.hidden, for: .navigationBar)
            }
            .tabItem { Label("Queue", systemImage: "list.bullet.rectangle") }.tag(0)

            NavigationStack { LibraryView().navigationTitle(Text("Library")) }
                .tabItem { Label("Library", systemImage: "square.grid.2x2") }.tag(1)

            NavigationStack { SettingsView() }
                .tabItem { Label("Computer", systemImage: "desktopcomputer") }.tag(2)
        }
    }
}

// MARK: unfolded – queue left, preview right
struct SplitLayout: View {
    @EnvironmentObject var model: AppModel
    var hinge: HingeState
    @State private var settings = false

    var body: some View {
        GeometryReader { g in
            HStack(spacing: 0) {
                ScrollView {
                    VStack(spacing: 14) {
                        Header(onSettings: { settings = true })
                        GPUCard()
                        CommandBar()
                        QueueList(navigates: false)
                    }.padding(.horizontal, 16).padding(.bottom, 24)
                }
                .refreshable { await model.refresh() }
                .frame(width: g.size.width * 0.48)
                .background { ZStack { T.bg; Glow() }.ignoresSafeArea() }
                Rectangle().fill(T.line).frame(width: 1).ignoresSafeArea(edges: .bottom)
                PreviewPane().frame(maxWidth: .infinity)
            }
        }
        .sheet(isPresented: $settings) { NavigationStack { SettingsView() }.presentationDetents([.large]) }
    }
}

struct Header: View {
    @EnvironmentObject var model: AppModel
    var onSettings: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: 12) {
            LogoT(size: 34)
            VStack(alignment: .leading, spacing: 3) {
                Wordmark(size: 13)
                HStack(spacing: 6) {
                    Circle().fill(dot).frame(width: 7, height: 7)
                    Text(statusText).font(.system(size: 12)).foregroundStyle(T.text2).lineLimit(1)
                }
            }
            Spacer()
            if let onSettings {
                Button(action: onSettings) { Image(systemName: "desktopcomputer").font(.system(size: 17)).foregroundStyle(T.text2) }
                    .accessibilityLabel(Text("Computer"))
            }
        }.padding(.top, 8)
    }

    var dot: Color {
        switch model.link { case .online: return T.green; case .connecting: return T.blue; default: return T.coral }
    }
    var statusText: String {
        let name = model.server?.name ?? model.pairing?.name ?? "Toravo OS"
        switch model.link {
        case .online: return String(localized: "Connected to \(name)")
        case .connecting: return String(localized: "Connecting to \(name) …")
        case .revoked: return String(localized: "This phone was removed on the computer")
        default: return String(localized: "\(name) is offline")
        }
    }
}
