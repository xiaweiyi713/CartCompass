import SwiftUI

/// Read-only view of an archived conversation, opened from the sidebar history.
struct ConversationDetailView: View {
    let conversation: StoredConversation
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Theme.Spacing.md) {
                    ForEach(conversation.messages) { message in
                        ArchivedBubble(message: message)
                    }
                }
                .padding(.horizontal, Theme.Spacing.md)
                .padding(.vertical, Theme.Spacing.lg)
            }
            .scrollContentBackground(.hidden)
            .scrollIndicators(.hidden)
            .background(LiquidBackdrop())
            .navigationTitle(conversation.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}

private struct ArchivedBubble: View {
    let message: ArchivedMessage

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack {
            if isUser {
                Spacer(minLength: 48)
                Text(message.text)
                    .font(.callout)
                    .foregroundStyle(Theme.Color.onAccent)
                    .padding(.horizontal, 15)
                    .padding(.vertical, 11)
                    .background(Theme.Color.accent, in: .rect(cornerRadius: 20))
            } else {
                Text(message.text)
                    .font(.callout)
                    .foregroundStyle(.primary)
                    .padding(13)
                    .liquidGlass(radius: Theme.Radius.md, elevated: false)
                Spacer(minLength: 48)
            }
        }
    }
}
