import SwiftUI

@main
struct ShopGuideApp: App {
    @State private var chatModel = ChatViewModel()

    var body: some Scene {
        WindowGroup {
            ChatView(model: chatModel)
        }
    }
}
