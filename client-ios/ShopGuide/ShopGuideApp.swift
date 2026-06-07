import SwiftData
import SwiftUI

@main
struct ShopGuideApp: App {
    @State private var chatModel = ChatViewModel()
    @AppStorage("shopguide.appearance") private var appearanceRaw = AppearanceMode.dark.rawValue

    private var appearance: AppearanceMode {
        AppearanceMode(rawValue: appearanceRaw) ?? .system
    }

    var body: some Scene {
        WindowGroup {
            ChatView(model: chatModel)
                .preferredColorScheme(appearance.colorScheme)
        }
        .modelContainer(for: StoredConversation.self)
    }
}
