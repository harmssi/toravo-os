import SwiftUI
import AVKit
import Photos

/// Right column when unfolded: the job you tapped, else the newest result + library.
struct PreviewPane: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        Group {
            if let id = model.selectedJobID, model.jobs.contains(where: { $0.id == id }) {
                JobDetail(jobID: id, onClose: { withAnimation { model.selectedJobID = nil } })
                    .transition(.opacity)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        MicroLabel("Preview", color: T.violet).padding(.top, 14)
                        if let s = model.spotlight { MediaCard(media: s, large: true) }
                        LibraryGrid(columns: 2)
                    }.padding(.horizontal, 16).padding(.bottom, 24)
                }
            }
        }
    }
}

struct SpotlightCard: View {
    let media: Media
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            MicroLabel("Just finished", color: T.green)
            MediaCard(media: media)
        }
    }
}

/// Poster -> tap -> download (pinned) -> play / save / share.
struct MediaCard: View {
    @EnvironmentObject var model: AppModel
    let media: Media
    var large = false
    @State private var local: URL?
    @State private var loading = false
    @State private var saved = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ZStack {
                if let local, media.isVideo {
                    LoopingPlayer(url: local).aspectRatio(9 / 16, contentMode: .fit)
                } else if let local, media.isImage, let img = UIImage(contentsOfFile: local.path) {
                    Image(uiImage: img).resizable().scaledToFit()
                } else {
                    Poster(media: media).overlay {
                        if loading { ProgressView().tint(.white).scaleEffect(1.3) }
                        else if media.isVideo { Image(systemName: "play.circle.fill").font(.system(size: 48)).foregroundStyle(.white.opacity(0.92)).shadow(radius: 8) }
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: large ? 520 : 420)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .contentShape(Rectangle())
            .onTapGesture { Task { await load() } }
            .accessibilityElement(children: .ignore).accessibilityAddTraits(.isButton)
            .accessibilityLabel(Text(media.name)).accessibilityIdentifier("media-\(media.name)")

            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(media.name).font(.system(size: 13, weight: .semibold, design: .monospaced)).foregroundStyle(T.text).lineLimit(1)
                    if let s = media.size { Text(ByteCountFormatter.string(fromByteCount: s, countStyle: .file)).font(.system(size: 11)).foregroundStyle(T.text3) }
                }
                Spacer()
                Button { Task { await saveToPhotos() } } label: {
                    Label(saved ? String(localized: "Saved") : String(localized: "Save"), systemImage: saved ? "checkmark" : "square.and.arrow.down")
                        .font(.system(size: 13, weight: .semibold)).padding(.horizontal, 12).padding(.vertical, 8)
                        .background(T.gradient, in: Capsule()).foregroundStyle(.white)
                }.buttonStyle(.plain).disabled(!(media.isVideo || media.isImage)).accessibilityIdentifier("saveButton")
                if let local {
                    ShareLink(item: local) { Image(systemName: "square.and.arrow.up").font(.system(size: 15, weight: .semibold)).padding(8)
                        .background(T.panel2, in: Circle()).foregroundStyle(T.text) }
                }
            }
            if let error { Text(error).font(.system(size: 12)).foregroundStyle(T.coral) }
        }
        .padding(10)
        .background(T.panel, in: RoundedRectangle(cornerRadius: T.radius))
        .overlay(RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.line))
        .task(id: media.id) { if large && media.isVideo { await load() } }
    }

    func load() async {
        guard local == nil, !loading, let c = model.client else { return }
        loading = true
        defer { loading = false }
        do { local = try await c.download(media) } catch { self.error = (error as? LocalizedError)?.errorDescription }
    }

    func saveToPhotos() async {
        await load()
        guard let local else { return }
        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized || status == .limited else {
            error = String(localized: "Allow Toravo to add to your photos in Settings.")
            return
        }
        do {
            try await PHPhotoLibrary.shared().performChanges {
                if media.isVideo { PHAssetChangeRequest.creationRequestForAssetFromVideo(atFileURL: local) }
                else { PHAssetChangeRequest.creationRequestForAssetFromImage(atFileURL: local) }
            }
            withAnimation { saved = true }
        } catch { self.error = error.localizedDescription }
    }
}

struct LoopingPlayer: View {
    let url: URL
    @State private var player: AVQueuePlayer?
    @State private var looper: AVPlayerLooper?
    var body: some View {
        VideoPlayer(player: player)
            .onAppear {
                let p = AVQueuePlayer()
                p.isMuted = Notify.muted
                looper = AVPlayerLooper(player: p, templateItem: AVPlayerItem(url: url))
                player = p
                p.play()
            }
            .onDisappear { player?.pause() }
    }
}

final class PosterCache {
    static let shared = NSCache<NSString, UIImage>()
}

struct Poster: View {
    @EnvironmentObject var model: AppModel
    let media: Media
    @State private var img: UIImage?
    var body: some View {
        ZStack {
            Rectangle().fill(T.panel2)
            if let img { Image(uiImage: img).resizable().scaledToFill() }
            else { Image(systemName: kindIcon(media.kind)).font(.system(size: 28)).foregroundStyle(T.text3) }
        }
        .aspectRatio(media.kind == "shorts" ? 9 / 16 : 16 / 9, contentMode: .fit)
        .clipped()
        .task(id: media.id) {
            if let c = PosterCache.shared.object(forKey: media.id as NSString) { img = c; return }
            guard let p = media.poster, let d = try? await model.client?.data(p), let i = UIImage(data: d) else { return }
            PosterCache.shared.setObject(i, forKey: media.id as NSString)
            img = i
        }
    }
}

struct LibraryGrid: View {
    @EnvironmentObject var model: AppModel
    var columns = 2
    @State private var kind = "all"
    @State private var open: Media?

    var items: [Media] { model.media.filter { kind == "all" ? $0.kind != "song" : $0.kind == kind } }   // songs + stems live in the Studio

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("", selection: $kind) {
                Text("All").tag("all")
                Text("Shorts").tag("shorts")
                Text("Videos").tag("video")
                Text("Thumbnails").tag("thumbnail")
            }.pickerStyle(.segmented)
            if items.isEmpty {
                Text("No results yet.").font(.system(size: 14)).foregroundStyle(T.text3).padding(.vertical, 20)
            }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: columns), spacing: 10) {
                ForEach(items) { m in
                    Button { open = m } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Poster(media: m).clipShape(RoundedRectangle(cornerRadius: 8))
                            Text(m.name).font(.system(size: 11, design: .monospaced)).foregroundStyle(T.text2).lineLimit(1)
                        }
                    }.buttonStyle(.plain)
                }
            }
        }
        .sheet(item: $open) { m in
            ScrollView { MediaCard(media: m, large: true).padding(16) }
                .background(T.bg)
                .presentationDetents([.large])
        }
    }
}

struct LibraryView: View {
    var body: some View {
        ScrollView { LibraryGrid(columns: 2).padding(16) }
            .background { ZStack { T.bg; Glow() }.ignoresSafeArea() }
    }
}
