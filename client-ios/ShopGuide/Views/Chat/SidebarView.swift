import SwiftData
import SwiftUI

/// Slide-in navigation drawer: quick entries + appearance on top, a divider,
/// then persisted chat history below. New chats archive the current one.
struct SidebarView: View {
    @Bindable var model: ChatViewModel
    @Binding var isOpen: Bool
    let topInset: CGFloat
    var openProfile: () -> Void
    var openModelBrain: () -> Void
    var openPrivacy: () -> Void

    @AppStorage("shopguide.appearance") private var appearanceRaw = AppearanceMode.dark.rawValue
    @Environment(\.modelContext) private var context
    @Query(sort: \StoredConversation.createdAt, order: .reverse) private var conversations: [StoredConversation]
    @State private var selected: StoredConversation?
    @State private var pendingDeletion: StoredConversation?

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            header

            VStack(spacing: 2) {
                SidebarRow(title: "我的偏好", systemImage: "person.crop.circle", action: openProfile)
                SidebarRow(title: "对话模型", systemImage: "brain", action: openModelBrain)
                SidebarRow(title: "隐私与合规", systemImage: "lock.shield", action: openPrivacy)
            }

            appearancePicker

            Divider().overlay(Theme.Color.cardStroke)

            Text("历史对话")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            history

            Spacer(minLength: 0)
        }
        .padding(.horizontal, Theme.Spacing.md)
        .padding(.top, topInset + Theme.Spacing.md)
        .padding(.bottom, Theme.Spacing.lg)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .sheet(item: $selected) { conversation in
            ConversationDetailView(conversation: conversation) {
                selected = nil
                pendingDeletion = conversation
            }
        }
        .alert("删除历史对话？", isPresented: deleteAlertBinding) {
            Button("删除", role: .destructive) {
                if let pendingDeletion {
                    deleteConversation(pendingDeletion)
                }
                pendingDeletion = nil
            }
            Button("取消", role: .cancel) {
                pendingDeletion = nil
            }
        } message: {
            Text("删除后无法恢复。")
        }
    }

    private var header: some View {
        HStack {
            Label("智购罗盘", systemImage: "sparkle.magnifyingglass")
                .font(.headline)
            Spacer()
            Button(action: startNewChat) {
                Image(systemName: "square.and.pencil")
                    .font(.headline)
                    .foregroundStyle(.primary)
                    .frame(width: 40, height: 40)
                    .background(.ultraThinMaterial, in: .circle)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("新对话")
        }
    }

    private var appearancePicker: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text("外观")
                .font(.caption)
                .foregroundStyle(.secondary)
            Picker("外观", selection: $appearanceRaw) {
                ForEach(AppearanceMode.allCases) { mode in
                    Text(mode.label).tag(mode.rawValue)
                }
            }
            .pickerStyle(.segmented)
        }
    }

    @ViewBuilder private var history: some View {
        if conversations.isEmpty {
            Text("还没有历史对话。点右上角“新对话”会把当前会话归档到这里。")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        } else {
            ScrollView {
                LazyVStack(spacing: 4) {
                    ForEach(conversations) { conversation in
                        HistoryRow(
                            conversation: conversation,
                            open: {
                                selected = conversation
                            },
                            delete: {
                                pendingDeletion = conversation
                            }
                        )
                        .contextMenu {
                            Button("删除", systemImage: "trash", role: .destructive) {
                                pendingDeletion = conversation
                            }
                        }
                    }
                }
            }
            .scrollIndicators(.hidden)
        }
    }

    private func startNewChat() {
        if model.hasUserMessages {
            context.insert(StoredConversation(title: model.conversationTitle, messages: model.archivedMessages))
            try? context.save()
        }
        model.startNewConversation()
        withAnimation(Theme.Motion.spring) { isOpen = false }
    }

    private var deleteAlertBinding: Binding<Bool> {
        Binding(
            get: { pendingDeletion != nil },
            set: { isPresented in
                if !isPresented {
                    pendingDeletion = nil
                }
            }
        )
    }

    private func deleteConversation(_ conversation: StoredConversation) {
        if selected?.id == conversation.id {
            selected = nil
        }
        context.delete(conversation)
        try? context.save()
    }
}

private struct SidebarRow: View {
    let title: String
    let systemImage: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.body)
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
    }
}

private struct HistoryRow: View {
    let conversation: StoredConversation
    let open: () -> Void
    let delete: () -> Void

    var body: some View {
        Button(action: open) {
            VStack(alignment: .leading, spacing: 2) {
                Text(conversation.title)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Text(conversation.preview)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            .padding(.trailing, 42)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .padding(.horizontal, Theme.Spacing.sm)
        .padding(.vertical, Theme.Spacing.xs)
        .background(.ultraThinMaterial, in: .rect(cornerRadius: Theme.Radius.sm))
        .contentShape(.rect)
        .overlay(alignment: .trailing) {
            Button(action: delete) {
                Image(systemName: "trash")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 34, height: 34)
                    .background(.ultraThinMaterial, in: .circle)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("删除历史对话 \(conversation.title)")
            .padding(.trailing, Theme.Spacing.xs)
        }
    }
}
