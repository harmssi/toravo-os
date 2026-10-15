import SwiftUI

/// Toravo OS design tokens (brand/tokens.css, measured from the trailer).
enum T {
    static let bg = Color(hex: 0x07070d)
    static let bg2 = Color(hex: 0x0c0c14)
    static let panel = Color(hex: 0x12111c)
    static let panel2 = Color(hex: 0x181626)
    static let line = Color(hex: 0x24213a)
    static let glow = Color(hex: 0x49317f)
    static let text = Color(hex: 0xf2f2f7)
    static let text2 = Color(hex: 0xa9a8bd)
    static let text3 = Color(hex: 0x6c6a85)
    static let violet = Color(hex: 0x8a5cf6)
    static let blue = Color(hex: 0x6f9be0)
    static let cyan = Color(hex: 0x5ab0d0)
    static let coral = Color(hex: 0xd8806a)
    static let red = Color(hex: 0xe5484d)
    static let green = Color(hex: 0x4cc38a)
    static let gradient = LinearGradient(stops: [.init(color: violet, location: 0), .init(color: blue, location: 0.55), .init(color: cyan, location: 1)],
                                         startPoint: .leading, endPoint: .trailing)
    static let radius: CGFloat = 12
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xff) / 255, green: Double((hex >> 8) & 0xff) / 255, blue: Double(hex & 0xff) / 255)
    }
}

/// Folded (one column) or unfolded (queue left, preview right). Width decides – that also covers normal iPhones, Split View
/// and the hinge in any position; the hinge status only adds the "partly open" table-top hint.
enum LayoutMode: Equatable {
    case single, split
    static let splitMinWidth: CGFloat = 600
    static func forWidth(_ w: CGFloat) -> LayoutMode { w >= splitMinWidth ? .split : .single }
}

struct MicroLabel: View {
    let text: String
    var color: Color = T.text3
    init(_ text: String, color: Color = T.text3) { self.text = text; self.color = color }
    var body: some View {
        Text(String(localized: String.LocalizationValue(text)).uppercased()).font(.system(size: 10.5, weight: .semibold)).tracking(3.2).foregroundStyle(color).lineLimit(1)
    }
}

struct Panel<Content: View>: View {
    var padding: CGFloat = 14
    @ViewBuilder var content: Content
    var body: some View {
        content.padding(padding).frame(maxWidth: .infinity, alignment: .leading)
            .background(T.panel, in: RoundedRectangle(cornerRadius: T.radius))
            .overlay(RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.line, lineWidth: 1))
    }
}

struct GradientBar: View {
    var value: Double
    var height: CGFloat = 4
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(T.panel2)
                Capsule().fill(T.gradient).frame(width: max(height, g.size.width * min(1, max(0, value))))
            }
        }.frame(height: height)
    }
}

struct PrimaryButton: View {
    let title: String
    var busy = false
    var id = ""
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if busy { ProgressView().tint(.white) }
                Text(title).font(.system(size: 16, weight: .bold))
            }.frame(maxWidth: .infinity).padding(.vertical, 13)
                .background(T.gradient, in: RoundedRectangle(cornerRadius: T.radius)).foregroundStyle(.white)
        }.buttonStyle(.plain).disabled(busy).accessibilityIdentifier(id)
    }
}

struct Wordmark: View {
    var size: CGFloat = 13
    var body: some View {
        HStack(spacing: 0) {
            Text("TORAVO").foregroundStyle(T.text)
            Text("/").foregroundStyle(T.violet)
            Text("OS").foregroundStyle(T.text)
        }.font(.system(size: size, weight: .semibold)).tracking(size * 0.34)
    }
}

struct LogoT: View {
    var size: CGFloat = 34
    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.24).fill(Color(hex: 0x1a172c))
            .overlay(RoundedRectangle(cornerRadius: size * 0.24).strokeBorder(Color(hex: 0x342e54), lineWidth: 1))
            .overlay(Text("T").font(.system(size: size * 0.58, weight: .heavy))
                .foregroundStyle(LinearGradient(colors: [Color(hex: 0x9d7cf0), T.blue], startPoint: .top, endPoint: .bottom)))
            .frame(width: size, height: size)
            .shadow(color: T.violet.opacity(0.55), radius: size * 0.35)
    }
}

/// The soft violet bloom from the trailer, behind headers.
struct Glow: View {
    var body: some View {
        RadialGradient(colors: [T.glow.opacity(0.55), .clear], center: .top, startRadius: 0, endRadius: 360).ignoresSafeArea()
    }
}

func stateColor(_ s: String) -> Color {
    switch s {
    case "running": return T.cyan
    case "done": return T.green
    case "failed", "needs_tool": return T.coral
    case "paused": return T.blue
    default: return T.text3
    }
}

func stateLabel(_ s: String) -> String {
    switch s {
    case "queued": return String(localized: "waiting")
    case "running": return String(localized: "running")
    case "paused": return String(localized: "paused")
    case "done": return String(localized: "done")
    case "failed": return String(localized: "failed")
    case "needs_tool": return String(localized: "tool missing")
    case "cancelled": return String(localized: "cancelled")
    default: return s
    }
}

func kindIcon(_ k: String) -> String {
    switch k {
    case "song": return "music.note"
    case "voice": return "waveform"
    case "video": return "film"
    case "shorts": return "rectangle.portrait.on.rectangle.portrait"
    case "thumbnail": return "photo"
    case "stems": return "slider.vertical.3"
    case "master": return "dial.medium"
    case "transcribe": return "captions.bubble"
    case "stream": return "dot.radiowaves.left.and.right"
    default: return "sparkles"
    }
}
