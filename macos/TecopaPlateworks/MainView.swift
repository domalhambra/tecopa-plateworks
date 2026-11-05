import SwiftUI

/// The one window: a sidebar of Studio, Orders, Plates and Engine (phase 2 spec,
/// decision 1). Until the engine answers, the window says what it is doing.
struct MainView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationSplitView {
            List(Pane.allCases, selection: Binding(get: { model.pane }, set: { if let p = $0 { model.pane = p } })) { pane in
                Label(pane.title, systemImage: pane.symbol).tag(pane)
            }
            .navigationSplitViewColumnWidth(min: 160, ideal: 180, max: 220)
            .safeAreaInset(edge: .bottom) { EngineBadge().padding(10) }
        } detail: {
            switch model.engine {
            case .starting(let what):
                VStack(spacing: 12) {
                    ProgressView()
                    Text(what).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            case .failed(let title, let message):
                ContentUnavailableView {
                    Label(title, systemImage: "exclamationmark.triangle")
                } description: {
                    Text(message).textSelection(.enabled)
                } actions: {
                    Button("Try Again") { Task { await model.launch() } }
                    Button("Show the Log") { model.pane = .engine; model.engine = .ready(adopted: false) }
                }
            case .ready:
                switch model.pane {
                case .studio: StudioView()
                case .orders: OrdersView()
                case .plates: PlatesView()
                case .engine: EngineView()
                }
            }
        }
        .navigationTitle(model.pane.title)
    }
}

/// The engine's state in a line under the sidebar.
struct EngineBadge: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(text).font(.caption).foregroundStyle(.secondary)
            Spacer()
        }
        .accessibilityElement(children: .combine)
    }

    private var color: Color {
        switch model.engine {
        case .ready: return .green
        case .starting: return .orange
        case .failed: return .red
        }
    }

    private var text: String {
        switch model.engine {
        case .ready(let adopted): return adopted ? "Engine on 8848 (adopted)" : "Engine on 8848"
        case .starting: return "Engine starting"
        case .failed: return "Engine stopped"
        }
    }
}
