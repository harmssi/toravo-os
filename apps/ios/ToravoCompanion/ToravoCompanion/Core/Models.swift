import Foundation

// API v1 of the toravo-companion service (docs/COMPANION.md). Everything optional that the PC may leave out.

struct ServerInfo: Codable, Equatable {
    var name: String
    var id: String
    var version: String?
}

struct GPU: Codable, Equatable {
    var name: String
    var util: Double
    var vram_used: Double
    var vram_total: Double
    var temp: Double
    static let empty = GPU(name: "–", util: 0, vram_used: 0, vram_total: 0, temp: 0)
}

struct Media: Codable, Identifiable, Hashable {
    var id: String
    var kind: String
    var name: String
    var size: Int64?
    var mtime: Double?
    var type: String          // video | image | audio
    var url: String
    var poster: String?

    var isVideo: Bool { type == "video" }
    var isImage: Bool { type == "image" }
    var fileExtension: String { (name as NSString).pathExtension.lowercased() }
}

struct Job: Codable, Identifiable, Equatable {
    var id: String
    var kind: String
    var title: String
    var subject: String?
    var state: String
    var progress: Double
    var step: String?
    var created: Double?
    var started: Double?
    var finished: Double?
    var error: String?
    var outputs: [Media]?
    var can_pause: Bool?
    var can_resume: Bool?
    var can_cancel: Bool?

    var isActive: Bool { state == "running" || state == "queued" || state == "paused" }
    var media: [Media] { outputs ?? [] }
}

struct Status: Codable {
    var server: ServerInfo
    var gpu: GPU
    var jobs: [Job]
    var events_seq: Int64?
    var time: Double?
}

struct Event: Codable, Identifiable {
    var seq: Int64
    var time: Double?
    var type: String
    var job_id: String
    var title: String
    var kind: String?
    var outputs: [Media]?
    var id: Int64 { seq }
}

struct EventsReply: Codable {
    var seq: Int64
    var events: [Event]
}

struct PlanStep: Codable, Identifiable, Hashable {
    var kind: String
    var title: String
    var ready: Bool?
    var engine: String?
    var count: Int?
    var id: String { kind + title }
}

struct Plan: Codable, Identifiable {
    var plan_id: String
    var title: String
    var subject: String?
    var provider: String?
    var ready: Bool?
    var steps: [PlanStep]
    var id: String { plan_id }
}

struct RunReply: Codable { var jobs: [String] }
struct JobReply: Codable { var ok: Bool?; var job: Job? }
struct MediaReply: Codable { var items: [Media] }
struct Hello: Codable { var name: String; var version: String?; var id: String; var api: Int? }
struct PairReply: Codable { var token: String; var device_id: String; var server: ServerInfo }
struct APIErrorBody: Codable { var error: String; var message: String? }

/// What the app remembers about the paired PC (the token itself lives in the Keychain).
struct Pairing: Codable, Equatable {
    var serverID: String
    var name: String
    var hosts: [String]
    var port: Int
    var fingerprint: String
    var deviceID: String
}
