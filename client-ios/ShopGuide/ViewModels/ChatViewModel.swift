import Foundation

@Observable
final class ChatViewModel {
    var inputText = ""
    var messages: [ChatMessage] = [
        ChatMessage(role: .assistant, text: "你好，我是智能导购。可以告诉我预算、类目、偏好或排除条件，我会只基于商品库推荐。")
    ]
    var cart: CartState
    var latestOrder: OrderState?
    var checkoutSession: CheckoutSessionState?
    var checkoutURL: URL?
    var profile = UserProfile.empty
    var llmStatus = LLMStatus.empty
    var llmAPIKey = ""
    var llmModel = "deepseek-chat"
    var llmBaseURL = "https://api.deepseek.com"
    var llmTestMessage: String?
    var conversationModeLabel = "普通聊天"
    var speechOutputText: String?
    var isStreaming = false
    var isImageSearching = false
    var isCartUpdating = false
    var isProfileLoading = false
    var isLLMUpdating = false
    var errorMessage: String?

    private(set) var sessionID: String
    private let service = ChatStreamService()
    private let cartService = CartAPIService()
    private let imageSearchService = ImageSearchService()
    private let profileService = ProfileAPIService()
    private let llmService = LLMAPIService()
    private var assistantMessageID: UUID?

    init() {
        let initialSessionID = Self.makeSessionID()
        self.sessionID = initialSessionID
        self.cart = CartState(sessionID: initialSessionID, items: [], totalPrice: 0)
    }

    var hasLLMAPIKey: Bool {
        !sanitizedLLMAPIKey().isEmpty
    }

    // MARK: - Conversations / history

    var hasUserMessages: Bool {
        messages.contains { $0.role == .user }
    }

    /// Short title for the history list, derived from the first user message.
    var conversationTitle: String {
        let firstUser = messages.first { $0.role == .user }?.text
        let raw = (firstUser ?? messages.first?.text ?? "新对话").trimmingCharacters(in: .whitespacesAndNewlines)
        return raw.isEmpty ? "新对话" : String(raw.prefix(24))
    }

    /// Text-bearing turns to archive into history (cards/tool messages skipped).
    var archivedMessages: [ArchivedMessage] {
        messages.compactMap { message in
            guard message.role == .user || message.role == .assistant else { return nil }
            let text = message.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { return nil }
            return ArchivedMessage(role: message.role.rawValue, text: message.text)
        }
    }

    /// Starts a fresh conversation. A new `sessionID` gives the backend a clean
    /// session, so the agent no longer remembers the previous turn's products,
    /// clarifications, or cart — i.e. context is reset.
    @MainActor
    func startNewConversation() {
        sessionID = Self.makeSessionID()
        inputText = ""
        messages = [ChatMessage(role: .assistant, text: "你好，我是智能导购。可以告诉我预算、类目、偏好或排除条件，我会只基于商品库推荐。")]
        cart = CartState(sessionID: sessionID, items: [], totalPrice: 0)
        latestOrder = nil
        checkoutSession = nil
        checkoutURL = nil
        profile = .empty
        conversationModeLabel = "普通聊天"
        speechOutputText = nil
        assistantMessageID = nil
    }

    private static func makeSessionID() -> String {
        "ios-\(UUID().uuidString.prefix(8))"
    }

    @MainActor
    func send() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isStreaming else { return }
        inputText = ""
        messages.append(ChatMessage(role: .user, text: text))
        let assistant = ChatMessage(role: .assistant)
        assistantMessageID = assistant.id
        messages.append(assistant)
        isStreaming = true

        Task {
            do {
                for try await event in service.stream(sessionID: sessionID, message: text) {
                    await MainActor.run {
                        handle(event)
                    }
                }
                await MainActor.run {
                    if isStreaming {
                        isStreaming = false
                    }
                }
            } catch {
                await MainActor.run {
                    appendRecoveryNotice(.networkFailure(message: "这次消息没有连上后端：\(error.localizedDescription)"))
                    isStreaming = false
                }
            }
        }
    }

    @MainActor
    func sendQuickPrompt(_ prompt: String) {
        inputText = prompt
        send()
    }

    @MainActor
    private func handle(_ event: ChatStreamEvent) {
        switch event {
        case .token(let token):
            appendAssistantToken(token)
        case .products(let products):
            messages.append(ChatMessage(role: .products, products: products))
        case .compare(let result):
            messages.append(ChatMessage(role: .compare, comparison: result))
        case .cart(let state):
            cart = state
            messages.append(ChatMessage(role: .cart, cart: state))
        case .plan(let plan):
            messages.append(ChatMessage(role: .plan, plan: plan))
        case .weather(let weather):
            messages.append(ChatMessage(role: .weather, weather: weather))
        case .profile(let updatedProfile):
            profile = updatedProfile
            messages.append(ChatMessage(role: .profile, profile: updatedProfile))
        case .fallback(let notice):
            appendRecoveryNotice(notice)
        case .done(let payload):
            if let mode = payload.mode {
                conversationModeLabel = Self.modeLabel(for: mode)
            }
            publishSpeechOutputIfNeeded()
            isStreaming = false
        case .error(let message):
            appendRecoveryNotice(.chatFailure(message: message))
            isStreaming = false
        }
    }

    @MainActor
    private func appendAssistantToken(_ token: String) {
        guard let assistantMessageID,
              let index = messages.firstIndex(where: { $0.id == assistantMessageID }) else {
            return
        }
        messages[index].text += token
    }

    @MainActor
    private func publishSpeechOutputIfNeeded() {
        guard let assistantMessageID,
              let message = messages.first(where: { $0.id == assistantMessageID }) else {
            return
        }
        let text = message.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        speechOutputText = text
    }

    @MainActor
    func addToCart(_ product: Product, sku: SKU? = nil) {
        let selectedSKU = sku ?? product.skus.first
        mutateCart {
            try await self.cartService.add(sessionID: self.sessionID, productID: product.productID, skuID: selectedSKU?.skuID)
        } successMessage: { state in
            ChatMessage(role: .cart, cart: state)
        }
    }

    @MainActor
    func updateCartItem(_ item: CartItem, quantity: Int) {
        mutateCart {
            try await self.cartService.update(sessionID: self.sessionID, productID: item.product.productID, skuID: item.selectedSKU?.skuID, quantity: quantity)
        } successMessage: { state in
            ChatMessage(role: .cart, cart: state)
        }
    }

    @MainActor
    func removeCartItem(_ item: CartItem) {
        mutateCart {
            try await self.cartService.remove(sessionID: self.sessionID, productID: item.product.productID, skuID: item.selectedSKU?.skuID)
        } successMessage: { state in
            ChatMessage(role: .cart, cart: state)
        }
    }

    @MainActor
    func clearCart() {
        mutateCart {
            try await self.cartService.clear(sessionID: self.sessionID)
        } successMessage: { state in
            ChatMessage(role: .assistant, text: "购物车已清空。", cart: state)
        }
    }

    @MainActor
    func checkoutCart(address: String = "默认地址") {
        guard !cart.items.isEmpty else {
            appendRecoveryNotice(.emptyCart)
            return
        }
        guard !isCartUpdating else { return }
        isCartUpdating = true
        Task {
            do {
                let order = try await cartService.checkout(sessionID: sessionID, address: address)
                await MainActor.run {
                    latestOrder = order
                    cart = CartState(sessionID: sessionID, items: [], totalPrice: 0)
                    let total = String(format: "%.0f", order.totalPrice)
                    messages.append(ChatMessage(role: .assistant, text: "订单已创建：\(order.orderID)。共 \(order.items.count) 件商品，合计 ¥\(total)，配送到\(order.address)。我也为这单找了可补充购买的配件/复购候选。"))
                    if !order.postPurchaseRecommendations.isEmpty {
                        messages.append(ChatMessage(role: .products, products: order.postPurchaseRecommendations))
                    }
                    isCartUpdating = false
                }
            } catch {
                await MainActor.run {
                    appendRecoveryNotice(.from(error, defaultNotice: .checkoutFailure(message: "下单失败：\(error.localizedDescription)")))
                    isCartUpdating = false
                }
            }
        }
    }

    @MainActor
    func beginSandboxCheckout(address: String = "默认地址") {
        guard !cart.items.isEmpty else {
            appendRecoveryNotice(.emptyCart)
            return
        }
        guard !isCartUpdating else { return }
        isCartUpdating = true
        Task {
            do {
                let checkout = try await cartService.createCheckoutSession(sessionID: sessionID, address: address)
                await MainActor.run {
                    checkoutSession = checkout
                    checkoutURL = URL(string: checkout.checkoutURL)
                    let total = String(format: "%.0f", checkout.totalAmount)
                    let review = checkout.review.prefix(2).joined(separator: " ")
                    messages.append(ChatMessage(role: .assistant, text: "已创建沙箱结算会话：\(checkout.checkoutSessionID)。应付 ¥\(total)。\(review)"))
                    isCartUpdating = false
                }
            } catch {
                await MainActor.run {
                    appendRecoveryNotice(.from(error, defaultNotice: .checkoutFailure(message: "创建结算页失败：\(error.localizedDescription)")))
                    isCartUpdating = false
                }
            }
        }
    }

    @MainActor
    func handleCheckoutCallback(_ url: URL) {
        guard url.scheme == "shopguide",
              url.host == "checkout",
              url.path == "/success",
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let orderID = components.queryItems?.first(where: { $0.name == "order_id" })?.value else {
            return
        }
        checkoutURL = nil
        isCartUpdating = true
        Task {
            do {
                let order = try await cartService.fetchOrder(orderID: orderID)
                await MainActor.run {
                    latestOrder = order
                    cart = CartState(sessionID: sessionID, items: [], totalPrice: 0)
                    let total = String(format: "%.0f", order.totalPrice)
                    messages.append(ChatMessage(role: .assistant, text: "沙箱支付已完成：\(order.orderID)。状态 \(order.paymentStatus)，合计 ¥\(total)。订单状态已从虚拟商城回传到 App。"))
                    if !order.postPurchaseRecommendations.isEmpty {
                        messages.append(ChatMessage(role: .products, products: order.postPurchaseRecommendations))
                    }
                    isCartUpdating = false
                }
            } catch {
                await MainActor.run {
                    appendRecoveryNotice(.from(error, defaultNotice: .checkoutFailure(message: "读取支付订单失败：\(error.localizedDescription)")))
                    isCartUpdating = false
                }
            }
        }
    }

    @MainActor
    func loadProfile() {
        guard !isProfileLoading else { return }
        isProfileLoading = true
        Task {
            do {
                let profile = try await profileService.fetch(sessionID: sessionID)
                await MainActor.run {
                    self.profile = profile
                    isProfileLoading = false
                }
            } catch {
                await MainActor.run {
                    errorMessage = "读取偏好失败：\(error.localizedDescription)"
                    isProfileLoading = false
                }
            }
        }
    }

    @MainActor
    func clearProfile() {
        guard !isProfileLoading else { return }
        isProfileLoading = true
        Task {
            do {
                let profile = try await profileService.clear(sessionID: sessionID)
                await MainActor.run {
                    self.profile = profile
                    messages.append(ChatMessage(role: .assistant, text: "长期偏好已清除。"))
                    isProfileLoading = false
                }
            } catch {
                await MainActor.run {
                    errorMessage = "清除偏好失败：\(error.localizedDescription)"
                    isProfileLoading = false
                }
            }
        }
    }

    @MainActor
    func loadLLMStatus() {
        guard !isLLMUpdating else { return }
        isLLMUpdating = true
        Task {
            do {
                let status = try await llmService.status(sessionID: sessionID)
                await MainActor.run {
                    llmStatus = status
                    if ["deepseek", "openai_compatible", "anthropic"].contains(status.provider),
                       let model = status.model,
                       !model.isEmpty {
                        llmModel = model
                    }
                    if ["deepseek", "openai_compatible", "anthropic"].contains(status.provider),
                       let baseURL = status.baseURL,
                       !baseURL.isEmpty {
                        llmBaseURL = baseURL
                    }
                    isLLMUpdating = false
                }
            } catch {
                await MainActor.run {
                    errorMessage = "读取模型状态失败：\(error.localizedDescription)"
                    isLLMUpdating = false
                }
            }
        }
    }

    @MainActor
    func testLLMConnection(provider: String = "deepseek", displayName: String = "DeepSeek") {
        let key = sanitizedLLMAPIKey()
        guard !key.isEmpty, !isLLMUpdating else { return }
        isLLMUpdating = true
        llmTestMessage = nil
        Task {
            do {
                let result = try await llmService.test(sessionID: sessionID, provider: provider, apiKey: key, model: llmModel, baseURL: llmBaseURL)
                await MainActor.run {
                    llmTestMessage = result.ok
                        ? "连接成功：\(displayName) / \(result.model ?? result.provider)，\(String(format: "%.0f", result.latencyMS)) ms"
                        : "连接失败：\(result.message)"
                    if !result.ok {
                        appendRecoveryNotice(result.fallback ?? .modelConfigFailure(message: result.message))
                    }
                    isLLMUpdating = false
                }
            } catch {
                await MainActor.run {
                    llmTestMessage = "连接失败：\(error.localizedDescription)"
                    appendRecoveryNotice(.from(error, defaultNotice: .modelConfigFailure(message: "连接失败：\(error.localizedDescription)")))
                    isLLMUpdating = false
                }
            }
        }
    }

    @MainActor
    func saveLLMConfig(provider: String = "deepseek", displayName: String = "DeepSeek") {
        let key = sanitizedLLMAPIKey()
        guard !key.isEmpty, !isLLMUpdating else { return }
        isLLMUpdating = true
        Task {
            do {
                let status = try await llmService.configure(sessionID: sessionID, provider: provider, apiKey: key, model: llmModel, baseURL: llmBaseURL)
                await MainActor.run {
                    llmStatus = status
                    llmTestMessage = status.configured ? "已启用 \(displayName) 作为当前会话模型大脑。" : "模型配置未启用。"
                    messages.append(ChatMessage(role: .assistant, text: "已切换到 \(displayName) / \(status.model ?? llmModel) 模型大脑。RAG、工具调用和防幻觉检查仍由后端统一控制。"))
                    isLLMUpdating = false
                }
            } catch {
                await MainActor.run {
                    llmTestMessage = "保存失败：\(error.localizedDescription)"
                    appendRecoveryNotice(.from(error, defaultNotice: .modelConfigFailure(message: "保存失败：\(error.localizedDescription)")))
                    isLLMUpdating = false
                }
            }
        }
    }

    private func sanitizedLLMAPIKey() -> String {
        let compact = llmAPIKey
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .filter { character in
                !character.isWhitespace
                    && character != "\u{200B}"
                    && character != "\u{200C}"
                    && character != "\u{200D}"
                    && character != "\u{FEFF}"
                    && character != "\u{2060}"
            }
        if let range = compact.range(of: #"sk-[A-Za-z0-9_-]+"#, options: .regularExpression) {
            return String(compact[range])
        }
        return String(compact)
    }

    private static func modeLabel(for mode: String) -> String {
        switch mode {
        case "general_chat":
            return "普通聊天"
        case "product_knowledge":
            return "商品知识"
        case "weather_query":
            return "天气查询"
        case "travel_weather_planning":
            return "旅行天气规划"
        case "weak_purchase_intent":
            return "需求澄清"
        case "transaction":
            return "购物车操作"
        default:
            return "导购推荐"
        }
    }

    @MainActor
    func clearLLMConfig() {
        guard !isLLMUpdating else { return }
        isLLMUpdating = true
        Task {
            do {
                let status = try await llmService.clear(sessionID: sessionID)
                await MainActor.run {
                    llmStatus = status
                    llmAPIKey = ""
                    llmTestMessage = "已恢复默认模型配置。"
                    messages.append(ChatMessage(role: .assistant, text: "已清除自定义模型配置，后续会回到默认模型或本地确定性回复。"))
                    isLLMUpdating = false
                }
            } catch {
                await MainActor.run {
                    llmTestMessage = "清除失败：\(error.localizedDescription)"
                    isLLMUpdating = false
                }
            }
        }
    }

    @MainActor
    private func mutateCart(
        operation: @escaping () async throws -> CartState,
        successMessage: @escaping (CartState) -> ChatMessage?
    ) {
        guard !isCartUpdating else { return }
        isCartUpdating = true
        Task {
            do {
                let state = try await operation()
                await MainActor.run {
                    cart = state
                    if let message = successMessage(state) {
                        messages.append(message)
                    }
                    isCartUpdating = false
                }
            } catch {
                await MainActor.run {
                    appendRecoveryNotice(.from(error, defaultNotice: .checkoutFailure(message: "购物车操作失败：\(error.localizedDescription)")))
                    isCartUpdating = false
                }
            }
        }
    }

    @MainActor
    func searchByImage(_ imageData: Data) {
        guard !isImageSearching else { return }
        let query = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        inputText = ""
        isImageSearching = true
        let userText = query.isEmpty ? "我上传了一张图片，帮我找相似商品" : "我上传了一张图片，并补充：\(query)"
        messages.append(ChatMessage(role: .user, text: userText))
        let assistant = ChatMessage(role: .assistant, text: query.isEmpty ? "正在分析图片并检索相似商品..." : "正在融合图片和文字需求检索商品...")
        messages.append(assistant)

        Task {
            do {
                let result = try await imageSearchService.search(imageData: imageData, query: query)
                await MainActor.run {
                    isImageSearching = false
                    if let fallback = result.fallback {
                        appendRecoveryNotice(fallback)
                    }
                    if result.products.isEmpty {
                        if result.fallback == nil {
                            appendRecoveryNotice(.imageEmpty)
                        }
                    } else {
                        let reply = query.isEmpty ? "我找到了几款视觉上相似的商品，结果基于本地商品图像库。" : "我按图片相似度和“\(query)”这条文字需求做了融合排序。"
                        messages.append(ChatMessage(role: .assistant, text: reply))
                        messages.append(ChatMessage(role: .products, products: result.products))
                    }
                }
            } catch {
                await MainActor.run {
                    isImageSearching = false
                    appendRecoveryNotice(.imageFailed(message: "图片搜索失败：\(error.localizedDescription)"))
                }
            }
        }
    }

    @MainActor
    private func appendRecoveryNotice(_ notice: FallbackNotice) {
        messages.append(ChatMessage(role: .fallback, fallback: notice))
    }
}

private extension FallbackNotice {
    static var emptyCart: FallbackNotice {
        FallbackNotice(
            code: "empty_cart_checkout",
            title: "购物车还是空的",
            message: "还没有可结算的商品。先让 Agent 推荐商品，加入购物车后再进入沙箱结算。",
            actions: [
                RecoveryAction(label: "推荐旅行用品", prompt: "我要去三亚度假，应该买些什么"),
                RecoveryAction(label: "推荐手机", prompt: "推荐手机")
            ],
            severity: "info"
        )
    }

    static var imageEmpty: FallbackNotice {
        FallbackNotice(
            code: "image_empty",
            title: "没有找到足够相似的图片商品",
            message: "我没有把这张图强行匹配到不可靠商品。你可以加一句文字需求，或换一张更清晰的商品主体图。",
            actions: [
                RecoveryAction(label: "加文字需求", prompt: "按这张图找同类商品，预算300以内"),
                RecoveryAction(label: "改用文字推荐", prompt: "描述一下商品类型和预算")
            ],
            severity: "info"
        )
    }

    static func imageFailed(message: String) -> FallbackNotice {
        FallbackNotice(
            code: "image_failed",
            title: "图片识别暂时失败",
            message: message,
            actions: [
                RecoveryAction(label: "改用文字描述", prompt: "我想找和图片类似的商品"),
                RecoveryAction(label: "推荐热门商品", prompt: "推荐最近适合入手的商品")
            ],
            severity: "warning"
        )
    }

    static func networkFailure(message: String) -> FallbackNotice {
        FallbackNotice(
            code: "network_failed",
            title: "网络连接失败",
            message: message,
            actions: [
                RecoveryAction(label: "重试导购", prompt: "推荐手机"),
                RecoveryAction(label: "看旅行方案", prompt: "我要去成都旅行，应该买什么")
            ],
            severity: "error"
        )
    }

    static func chatFailure(message: String) -> FallbackNotice {
        FallbackNotice(
            code: "chat_exception",
            title: "这次回复没有顺利完成",
            message: message,
            actions: [
                RecoveryAction(label: "换个说法", prompt: "推荐适合我的商品"),
                RecoveryAction(label: "只看本地推荐", prompt: "预算500，推荐实用商品")
            ],
            severity: "error"
        )
    }

    static func checkoutFailure(message: String) -> FallbackNotice {
        FallbackNotice(
            code: "checkout_failed",
            title: "交易流程没有完成",
            message: message,
            actions: [
                RecoveryAction(label: "查看购物车", prompt: "查看购物车"),
                RecoveryAction(label: "重新推荐", prompt: "重新推荐一组商品")
            ],
            severity: "warning"
        )
    }

    static func modelConfigFailure(message: String) -> FallbackNotice {
        FallbackNotice(
            code: "model_config_failed",
            title: "模型配置没有通过测试",
            message: message,
            actions: [
                RecoveryAction(label: "检查 Key/端点", prompt: "打开模型大脑设置"),
                RecoveryAction(label: "继续本地导购", prompt: "推荐手机")
            ],
            severity: "warning"
        )
    }

    static func from(_ error: Error, defaultNotice: FallbackNotice) -> FallbackNotice {
        if let recoverable = error as? RecoverableAPIError,
           let fallback = recoverable.fallback {
            return fallback
        }
        return defaultNotice
    }
}
