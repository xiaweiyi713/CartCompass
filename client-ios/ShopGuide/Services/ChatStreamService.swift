import Foundation

enum ChatStreamEvent {
    case token(String)
    case products([Product])
    case compare(ComparisonResult)
    case cart(CartState)
    case order(OrderState)
    case plan(ShoppingPlan)
    case weather(WeatherContext)
    case profile(UserProfile)
    case fallback(FallbackNotice)
    case done(ChatDonePayload)
    case error(String)
}

struct ChatDonePayload: Codable, Hashable {
    let ok: Bool?
    let mode: String?
    let needsClarification: Bool?
    let traceID: String?

    enum CodingKeys: String, CodingKey {
        case ok
        case mode
        case needsClarification = "needs_clarification"
        case traceID = "trace_id"
    }
}

struct ChatStreamService {
    private let client = APIClient()
    private let decoder = JSONDecoder()

    func stream(sessionID: String, profileUserID: String, message: String) -> AsyncThrowingStream<ChatStreamEvent, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    var request = URLRequest(url: client.baseURL.appending(path: "/api/chat/stream"))
                    request.httpMethod = "POST"
                    request.timeoutInterval = 60
                    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    request.httpBody = try JSONEncoder().encode(ChatRequest(sessionID: sessionID, profileUserID: profileUserID, message: message))

                    let (bytes, response) = try await URLSession.shared.bytes(for: request)
                    guard let httpResponse = response as? HTTPURLResponse, 200..<300 ~= httpResponse.statusCode else {
                        continuation.yield(.error("服务暂时不可用"))
                        continuation.finish()
                        return
                    }

                    var currentEvent = ""
                    var currentData = ""
                    for try await line in bytes.lines {
                        if line.hasPrefix("event:") {
                            currentEvent = String(line.dropFirst(6)).trimmingCharacters(in: .whitespaces)
                        } else if line.hasPrefix("data:") {
                            currentData = String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces)
                            if let event = decode(event: currentEvent, data: currentData) {
                                continuation.yield(event)
                            }
                            currentEvent = ""
                            currentData = ""
                        } else if line.isEmpty {
                            if let event = decode(event: currentEvent, data: currentData) {
                                continuation.yield(event)
                            }
                            currentEvent = ""
                            currentData = ""
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    private func decode(event: String, data: String) -> ChatStreamEvent? {
        guard let payload = data.data(using: .utf8) else { return nil }
        switch event {
        case "token":
            let token = (try? decoder.decode(String.self, from: payload)) ?? ""
            return .token(token)
        case "products":
            let products = (try? decoder.decode([Product].self, from: payload)) ?? []
            return .products(products)
        case "compare":
            guard let result = try? decoder.decode(ComparisonResult.self, from: payload) else { return nil }
            return .compare(result)
        case "cart":
            guard let cart = try? decoder.decode(CartState.self, from: payload) else { return nil }
            return .cart(cart)
        case "order":
            guard let order = try? decoder.decode(OrderState.self, from: payload) else { return nil }
            return .order(order)
        case "plan":
            guard let plan = try? decoder.decode(ShoppingPlan.self, from: payload) else { return nil }
            return .plan(plan)
        case "weather":
            guard let weather = try? decoder.decode(WeatherContext.self, from: payload) else { return nil }
            return .weather(weather)
        case "profile":
            guard let profile = try? decoder.decode(UserProfile.self, from: payload) else { return nil }
            return .profile(profile)
        case "fallback":
            guard let notice = try? decoder.decode(FallbackNotice.self, from: payload) else { return nil }
            return .fallback(notice)
        case "done":
            let payload = (try? decoder.decode(ChatDonePayload.self, from: payload)) ?? ChatDonePayload(ok: nil, mode: nil, needsClarification: nil, traceID: nil)
            return .done(payload)
        case "error":
            let message = (try? decoder.decode([String: String].self, from: payload))?["message"] ?? "未知错误"
            return .error(message)
        default:
            return nil
        }
    }
}

private struct ChatRequest: Encodable {
    let sessionID: String
    let profileUserID: String
    let message: String

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case profileUserID = "profile_user_id"
        case message
    }
}
