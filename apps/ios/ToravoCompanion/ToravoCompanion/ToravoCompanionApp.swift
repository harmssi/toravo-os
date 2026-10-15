import SwiftUI
import UserNotifications
import BackgroundTasks

@main
struct ToravoCompanionApp: App {
    @StateObject private var model: AppModel
    @Environment(\.scenePhase) private var phase
    private let notifications = ForegroundNotifications()

    init() {
        let m = AppModel()
        _model = StateObject(wrappedValue: m)
        UNUserNotificationCenter.current().delegate = notifications
        BGTaskScheduler.shared.register(forTaskWithIdentifier: AppModel.refreshTask, using: nil) { task in
            let work = Task { @MainActor in
                await m.backgroundRefresh()
                task.setTaskCompleted(success: true)
            }
            task.expirationHandler = { work.cancel() }
        }
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .preferredColorScheme(.dark)
                .tint(T.violet)
                .onOpenURL { url in
                    if let l = PairLink(url.absoluteString) { Task { await model.pair(with: l) } }
                }
        }
        .onChange(of: phase) { _, p in
            if p == .active { model.start() } else if p == .background { model.stop() }
        }
    }
}

/// Show "Done: …" also while the app is open.
final class ForegroundNotifications: NSObject, UNUserNotificationCenterDelegate {
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        Notify.muted ? [.banner, .list] : [.banner, .sound, .list]
    }
}
