import SwiftUI

struct GPUCard: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        let g = model.gpu
        Panel {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    MicroLabel(g.vram_total > 0 ? "GPU" : "CPU", color: T.violet)
                    Spacer()
                    Text(g.name).font(.system(size: 12, design: .monospaced)).foregroundStyle(T.text3).lineLimit(1)
                }
                HStack(alignment: .firstTextBaseline, spacing: 16) {
                    stat("\(Int(g.util.rounded())) %", String(localized: "load"))
                    if g.vram_total > 0 { stat(String(format: "%.1f GB", g.vram_used), String(localized: "of \(Int(g.vram_total.rounded())) GB VRAM")) }
                    if g.temp > 0 { stat("\(Int(g.temp)) °", String(localized: "temp")) }
                }
                GradientBar(value: g.util / 100, height: 4)
            }
        }
    }

    func stat(_ v: String, _ l: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(v).font(.system(size: 24, weight: .bold)).foregroundStyle(T.text).monospacedDigit()
                .contentTransition(.numericText())
            Text(l).font(.system(size: 11)).foregroundStyle(T.text3)
        }
    }
}

struct CommandBar: View {
    @EnvironmentObject var model: AppModel
    @FocusState private var focused: Bool

    var body: some View {
        Panel {
            VStack(alignment: .leading, spacing: 10) {
                MicroLabel("Command Bar", color: T.violet)
                HStack(spacing: 10) {
                    Image(systemName: "sparkle").foregroundStyle(T.violet)
                    TextField("", text: $model.command, prompt: Text("turn skyborne into a music video + 3 shorts").foregroundStyle(T.text3), axis: .vertical)
                        .font(.system(size: 16)).foregroundStyle(T.text).lineLimit(1...3)
                        .focused($focused).submitLabel(.go).accessibilityIdentifier("commandField")
                        .onSubmit { Task { await model.makePlan() } }
                    if model.planning { ProgressView().tint(T.violet) } else if !model.command.isEmpty {
                        Button { focused = false; Task { await model.makePlan() } } label: {
                            Image(systemName: "arrow.up.circle.fill").font(.system(size: 26)).foregroundStyle(T.violet)
                        }.accessibilityLabel(Text("Make a plan")).accessibilityIdentifier("planButton")
                    }
                }
                .padding(12).background(T.bg2, in: RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(focused ? T.violet : T.line))
                if let p = model.plan { PlanView(plan: p) }
                if let e = model.lastError, model.link == .online { Text(e).font(.system(size: 12)).foregroundStyle(T.coral) }
            }
        }
    }
}

struct PlanView: View {
    @EnvironmentObject var model: AppModel
    let plan: Plan
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                MicroLabel("Plan")
                Spacer()
                if let pr = plan.provider { Text(pr == "rules" ? String(localized: "built-in planner") : String(localized: "local AI")).font(.system(size: 11, design: .monospaced)).foregroundStyle(T.text3) }
            }
            ForEach(Array(plan.steps.enumerated()), id: \.offset) { i, s in
                HStack(spacing: 10) {
                    Text("\(i + 1)").font(.system(size: 12, weight: .bold, design: .monospaced)).foregroundStyle(T.violet).frame(width: 18)
                    Image(systemName: kindIcon(s.kind)).foregroundStyle(T.text2).frame(width: 20)
                    Text(s.title).font(.system(size: 14)).foregroundStyle(T.text).lineLimit(2)
                    Spacer(minLength: 4)
                    if s.ready == false { Text("tool missing").font(.system(size: 11)).foregroundStyle(T.coral) }
                    else { Image(systemName: "checkmark").font(.system(size: 11, weight: .bold)).foregroundStyle(T.green) }
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            HStack(spacing: 10) {
                Button { withAnimation { model.plan = nil } } label: {
                    Text("Discard").font(.system(size: 15, weight: .semibold)).padding(.vertical, 13).padding(.horizontal, 16)
                        .background(T.panel2, in: RoundedRectangle(cornerRadius: T.radius)).overlay(RoundedRectangle(cornerRadius: T.radius).strokeBorder(T.line))
                        .foregroundStyle(T.text2)
                }.buttonStyle(.plain)
                PrimaryButton(title: String(localized: "Start on my PC"), busy: model.starting, id: "startButton") { Task { await model.runPlan() } }
            }.padding(.top, 4)
        }
    }
}

struct QueueList: View {
    @EnvironmentObject var model: AppModel
    var navigates: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                MicroLabel("Render Queue")
                Spacer()
                Text("\(model.activeJobs.count) " + String(localized: "active")).font(.system(size: 12, design: .monospaced)).foregroundStyle(T.text3)
            }.padding(.top, 4)
            if model.jobs.isEmpty {
                Panel { Text(model.link == .online ? String(localized: "Nothing in the queue. Tell your PC what to make.") : String(localized: "Waiting for your computer …"))
                    .font(.system(size: 14)).foregroundStyle(T.text2) }
            }
            ForEach(model.activeJobs + model.finishedJobs.prefix(12)) { j in
                if navigates {
                    NavigationLink(value: j.id) { JobRow(job: j) }.buttonStyle(.plain).accessibilityIdentifier("job-\(j.kind)-\(j.state)")
                } else {
                    Button { withAnimation(.spring(duration: 0.3)) { model.selectedJobID = j.id } } label: {
                        JobRow(job: j, selected: model.selectedJobID == j.id)
                    }.buttonStyle(.plain).accessibilityIdentifier("job-\(j.kind)-\(j.state)")
                }
            }
        }
    }
}

struct JobRow: View {
    @EnvironmentObject var model: AppModel
    let job: Job
    var selected = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: kindIcon(job.kind)).font(.system(size: 15)).foregroundStyle(stateColor(job.state)).frame(width: 22)
                VStack(alignment: .leading, spacing: 2) {
                    Text(job.title).font(.system(size: 15, weight: .semibold)).foregroundStyle(T.text).lineLimit(1)
                    Text(job.step ?? "").font(.system(size: 12)).foregroundStyle(T.text3).lineLimit(1)
                }
                Spacer(minLength: 6)
                VStack(alignment: .trailing, spacing: 2) {
                    Text(stateLabel(job.state).uppercased()).font(.system(size: 9.5, weight: .bold)).tracking(1.6).foregroundStyle(stateColor(job.state))
                    if job.state == "running" { Text("\(Int(job.progress * 100)) %").font(.system(size: 12, design: .monospaced)).foregroundStyle(T.text2).contentTransition(.numericText()) }
                }
            }
            if job.state == "running" || job.state == "paused" { GradientBar(value: job.progress, height: 3).opacity(job.state == "paused" ? 0.45 : 1) }
        }
        .padding(12)
        .background(selected ? T.panel2 : T.panel, in: RoundedRectangle(cornerRadius: T.radius))
        .overlay(RoundedRectangle(cornerRadius: T.radius).strokeBorder(selected ? T.violet : T.line, lineWidth: selected ? 1.5 : 1))
        .contextMenu { JobActions(job: job) }
    }
}

struct JobActions: View {
    @EnvironmentObject var model: AppModel
    let job: Job
    var body: some View {
        if job.can_pause ?? (job.state == "queued") {
            Button { Task { await model.act(job, "pause") } } label: { Label("Pause", systemImage: "pause.fill") }
        }
        if job.can_resume ?? (job.state == "paused") {
            Button { Task { await model.act(job, "resume") } } label: { Label("Resume", systemImage: "play.fill") }
        }
        if job.can_cancel ?? job.isActive {
            Button(role: .destructive) { Task { await model.act(job, "cancel") } } label: { Label("Cancel", systemImage: "xmark") }
        }
    }
}

struct JobDetail: View {
    @EnvironmentObject var model: AppModel
    let jobID: String
    var onClose: (() -> Void)? = nil

    var body: some View {
        ScrollView {
            if let job = model.jobs.first(where: { $0.id == jobID }) {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        MicroLabel(job.kind, color: T.violet)
                        Spacer()
                        if let onClose { Button(action: onClose) { Image(systemName: "xmark.circle.fill").font(.system(size: 22)).foregroundStyle(T.text3) } }
                    }
                    Text(job.title).font(.system(size: 24, weight: .heavy)).foregroundStyle(T.text)
                    HStack(spacing: 8) {
                        Circle().fill(stateColor(job.state)).frame(width: 8, height: 8)
                        Text(stateLabel(job.state)).foregroundStyle(stateColor(job.state))
                        Text(job.step ?? "").foregroundStyle(T.text3).lineLimit(1)
                    }.font(.system(size: 13))
                    if job.isActive { GradientBar(value: job.progress, height: 5) }
                    if let e = job.error, !e.isEmpty { Text(e).font(.system(size: 13)).foregroundStyle(T.coral) }
                    HStack(spacing: 10) {
                        if job.can_pause ?? (job.state == "queued") { pill("Pause", "pause.fill") { await model.act(job, "pause") } }
                        if job.can_resume ?? (job.state == "paused") { pill("Resume", "play.fill") { await model.act(job, "resume") } }
                        if job.can_cancel ?? job.isActive { pill("Cancel", "xmark", T.coral) { await model.act(job, "cancel") } }
                    }
                    if !job.media.isEmpty {
                        MicroLabel("Results").padding(.top, 6)
                        ForEach(job.media) { m in MediaCard(media: m) }
                    }
                }.padding(16)
            } else {
                Text("This job is gone.").foregroundStyle(T.text3).padding(40)
            }
        }
        .background(Color.clear)
    }

    func pill(_ title: LocalizedStringKey, _ icon: String, _ color: Color = T.text, _ action: @escaping () async -> Void) -> some View {
        Button { Task { await action() } } label: {
            Label(title, systemImage: icon).font(.system(size: 14, weight: .semibold)).foregroundStyle(color)
                .padding(.horizontal, 14).padding(.vertical, 9).background(T.panel2, in: Capsule()).overlay(Capsule().strokeBorder(T.line))
        }.buttonStyle(.plain)
    }
}
