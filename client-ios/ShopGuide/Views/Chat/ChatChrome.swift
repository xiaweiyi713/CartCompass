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
                    .foregroundStyle(.white)
                    .frame(width: 32, height: 32)
                    .background(Theme.Color.accent.gradient, in: Circle())
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
                    Button(prompt) {
                        action(prompt)
                    }
                    .font(.footnote)
                    .buttonStyle(.plain)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(Color(.tertiarySystemBackground))
                    .clipShape(Capsule())
                    .overlay(
                        Capsule()
                            .stroke(Color.primary.opacity(0.07), lineWidth: 1)
                    )
                    .controlSize(.small)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .background(Color(.systemBackground).opacity(0.94))
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

    var body: some View {
        HStack(spacing: 8) {
            Button(action: openCamera) {
                Image(systemName: "camera")
                    .font(.system(size: 16, weight: .semibold))
                    .frame(width: 36, height: 36)
                    .background(Color(.tertiarySystemBackground))
                    .clipShape(Circle())
            }
            .buttonStyle(.borderless)
            .disabled(isStreaming || isImageSearching)
            .accessibilityLabel("拍照找货")

            PhotosPicker(selection: $selectedPhoto, matching: .images) {
                Image(systemName: isImageSearching ? "photo.badge.clock" : "photo")
                    .font(.system(size: 16, weight: .semibold))
                    .frame(width: 36, height: 36)
                    .background(Color(.tertiarySystemBackground))
                    .clipShape(Circle())
            }
            .buttonStyle(.borderless)
            .disabled(isStreaming || isImageSearching)
            .accessibilityLabel("上传图片")

            TextField("说出你的需求...", text: $text, axis: .vertical)
                .lineLimit(1...4)
                .textFieldStyle(.plain)
                .padding(.horizontal, 12)
                .padding(.vertical, 11)
                .background(Color(.secondarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(Color.primary.opacity(0.06), lineWidth: 1)
                )

            Button(action: toggleSpeech) {
                Image(systemName: isListening ? "mic.circle.fill" : "mic")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(isListening ? Color.red : Color.primary)
                    .frame(width: 36, height: 36)
                    .background(Color(.tertiarySystemBackground))
                    .clipShape(Circle())
            }
            .buttonStyle(.borderless)
            .disabled(isStreaming || isImageSearching)
            .accessibilityLabel(isListening ? "停止语音输入" : "开始语音输入")

            Button(action: send) {
                Image(systemName: isStreaming ? "hourglass" : "paperplane.fill")
                    .font(.system(size: 16, weight: .bold))
                    .frame(width: 40, height: 40)
            }
            .buttonStyle(.borderedProminent)
            .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isStreaming || isImageSearching)
            .accessibilityLabel("发送")
        }
        .padding(12)
        .background(.bar)
    }
}
