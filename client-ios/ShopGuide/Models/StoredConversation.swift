import Foundation
import SwiftData

/// A single archived chat turn kept for history display (text-bearing messages
/// only — product cards etc. are not replayed in the read-only history view).
struct ArchivedMessage: Codable, Identifiable, Hashable {
    var id = UUID()
    var role: String   // "user" / "assistant"
    var text: String
}

/// A persisted past conversation. SwiftData stores these in a local SQLite
/// database inside the app's private sandbox (Application Support), so history
/// survives relaunches without any third-party dependency.
@Model
final class StoredConversation {
    var id: UUID = UUID()
    var title: String = ""
    var createdAt: Date = Date.now
    /// JSON-encoded `[ArchivedMessage]`; kept as a blob to avoid a relationship.
    var messagesData: Data = Data()

    init(title: String, messages: [ArchivedMessage], createdAt: Date = .now) {
        self.id = UUID()
        self.title = title
        self.createdAt = createdAt
        self.messagesData = (try? JSONEncoder().encode(messages)) ?? Data()
    }

    var messages: [ArchivedMessage] {
        (try? JSONDecoder().decode([ArchivedMessage].self, from: messagesData)) ?? []
    }

    var preview: String {
        messages.first(where: { $0.role == "assistant" && !$0.text.isEmpty })?.text
            ?? messages.first?.text
            ?? ""
    }
}
