import PhotosUI
import SwiftUI

struct WelcomeAction: Identifiable {
    var id: String { prompt }
    let title: String
    let subtitle: String
    let icon: String
    let prompt: String
}

struct WelcomeActionPanel: View {
    let actions: [WelcomeAction]
    let sendPrompt: (String) -> Void

    private let columns = [
        GridItem(.flexible(minimum: 116), spacing: 10),
        GridItem(.flexible(minimum: 116), spacing: 10)
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "sparkle.magnifyingglass")
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Theme.Color.onAccent)
                    .frame(width: 32, height: 32)
                    .background(Theme.Color.accent.gradient, in: .circle)
                VStack(alignment: .leading, spacing: 3) {
                    Text("智能导购")
                        .font(.headline)
                    Text("预算 · 偏好 · 图片证据")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }

            LazyVGrid(columns: columns, alignment: .leading, spacing: 10) {
                ForEach(actions) { action in
                    Button {
                        sendPrompt(action.prompt)
                    } label: {
                        HStack(spacing: 9) {
                            Image(systemName: action.icon)
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(Theme.Color.accent)
                                .frame(width: 28, height: 28)
                                .background(Theme.Color.accent.opacity(0.12), in: Circle())
                            VStack(alignment: .leading, spacing: 2) {
                                Text(action.title)
                                    .font(.footnote.weight(.semibold))
                                    .foregroundStyle(.primary)
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.8)
                                Text(action.subtitle)
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.75)
                            }
                            Spacer(minLength: 0)
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, minHeight: 54, alignment: .leading)
                        .background(Color(.tertiarySystemBackground), in: RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous)
                                .stroke(Theme.Color.cardStroke, lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(14)
        .cardSurface(radius: Theme.Radius.lg)
    }
}

struct ModeStatusBar: View {
    let label: String
    let isStreaming: Bool

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.caption.weight(.semibold))
            Text(label)
                .font(.caption.weight(.semibold))
            if isStreaming {
                ProgressView()
                    .controlSize(.mini)
            }
            Spacer()
        }
        .foregroundStyle(.secondary)
        .padding(.horizontal, 16)
        .padding(.vertical, 7)
        .background(Color(.systemBackground).opacity(0.92))
        .accessibilityLabel("当前模式：\(label)")
    }

    private var icon: String {
        switch label {
        case "商品知识":
            return "book.closed"
        case "天气查询":
            return "cloud.sun"
        case "旅行天气规划":
            return "cloud.sun.rain"
        case "需求澄清":
            return "questionmark.bubble"
        case "购物车操作":
            return "cart"
        case "导购推荐":
            return "sparkle.magnifyingglass"
        default:
            return "bubble.left.and.bubble.right"
        }
    }
}

struct QuickPromptBar: View {
    let prompts: [String]
    let action: (String) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(prompts, id: \.self) { prompt in
                    Button {
                        action(prompt)
                    } label: {
                        Text(prompt)
                            .font(.footnote.weight(.medium))
                            .lineLimit(1)
                            .truncationMode(.tail)
                            .frame(maxWidth: 220, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(.ultraThinMaterial, in: .capsule)
                    .overlay(Capsule().strokeBorder(Theme.Color.cardStroke, lineWidth: 1))
                    .shadow(color: .black.opacity(0.12), radius: 8, y: 4)
                    .controlSize(.small)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 4)
        }
    }
}

struct ComposerView: View {
    @Binding var text: String
    @Binding var selectedPhoto: PhotosPickerItem?
    let isStreaming: Bool
    let isImageSearching: Bool
    let isListening: Bool
    let openCamera: () -> Void
    let toggleSpeech: () -> Void
    let send: () -> Void

    private var canSend: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isStreaming && !isImageSearching
    }

    var body: some View {
        HStack(spacing: 8) {
            Button(action: openCamera) {
                glyph("camera")
            }
            .buttonStyle(.borderless)
            .disabled(isStreaming || isImageSearching)
            .accessibilityLabel("拍照找货")

            PhotosPicker(selection: $selectedPhoto, matching: .images) {
                glyph(isImageSearching ? "photo.badge.clock" : "photo")
            }
            .buttonStyle(.borderless)
            .disabled(isStreaming || isImageSearching)
            .accessibilityLabel("上传图片")

            TextField("说出你的需求...", text: $text, axis: .vertical)
                .lineLimit(1...4)
                .textFieldStyle(.plain)
                .padding(.horizontal, 12)
                .padding(.vertical, 11)
                .background(.ultraThinMaterial, in: .rect(cornerRadius: 18))
                .overlay(
                    RoundedRectangle(cornerRadius: 18)
                        .strokeBorder(Theme.Color.cardStroke, lineWidth: 1)
                )

            Button(action: toggleSpeech) {
                glyph(isListening ? "mic.circle.fill" : "mic")
            }
            .buttonStyle(.borderless)
            .disabled(isStreaming || isImageSearching)
            .accessibilityLabel(isListening ? "停止语音输入" : "开始语音输入")

            Button(action: send) {
                Image(systemName: sendIcon)
                    .font(.system(size: 17, weight: .heavy))
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(sendForeground)
                    .frame(width: 42, height: 42)
                    .background(sendBackground, in: .circle)
                    .overlay(Circle().strokeBorder(sendStroke, lineWidth: 1))
                    .contentTransition(.symbolEffect(.replace))
            }
            .buttonStyle(.plain)
            .disabled(!canSend)
            .accessibilityLabel("发送")
        }
        .padding(10)
        .background(.ultraThinMaterial, in: .rect(cornerRadius: 28))
        .overlay(
            RoundedRectangle(cornerRadius: 28)
                .strokeBorder(Theme.Color.cardStroke, lineWidth: 1)
        )
    }

    /// Monochrome glass icon button face used for camera / photo / mic.
    private func glyph(_ name: String) -> some View {
        Image(systemName: name)
            .font(.system(size: 16, weight: .semibold))
            .foregroundStyle(.primary)
            .frame(width: 38, height: 38)
            .background(.ultraThinMaterial, in: .circle)
            .overlay(Circle().strokeBorder(Theme.Color.cardStroke, lineWidth: 1))
    }

    private var sendIcon: String {
        if isStreaming || isImageSearching { return "hourglass" }
        return canSend ? "arrow.up" : "arrow.up"
    }

    private var sendForeground: Color {
        canSend ? Theme.Color.onAccent : .secondary
    }

    private var sendBackground: some ShapeStyle {
        canSend ? AnyShapeStyle(Theme.Gradient.brand) : AnyShapeStyle(.ultraThinMaterial)
    }

    private var sendStroke: Color {
        canSend ? Theme.Color.glassHighlight : Theme.Color.cardStroke
    }
}
