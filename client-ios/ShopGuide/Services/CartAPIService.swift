import Foundation

struct CartAPIService {
    private let client = APIClient()
    private let decoder = JSONDecoder()

    func add(sessionID: String, productID: String, skuID: String? = nil, quantity: Int = 1) async throws -> CartState {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/cart/add"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(AddCartRequest(sessionID: sessionID, productID: productID, quantity: quantity, skuID: skuID))
        return try await sendCartRequest(request)
    }

    func update(sessionID: String, productID: String, skuID: String?, quantity: Int) async throws -> CartState {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/cart/update"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(UpdateCartRequest(sessionID: sessionID, productID: productID, quantity: quantity, skuID: skuID))
        return try await sendCartRequest(request)
    }

    func remove(sessionID: String, productID: String, skuID: String?) async throws -> CartState {
        var components = URLComponents(url: client.baseURL.appending(path: "/api/cart/\(sessionID)/\(productID)"), resolvingAgainstBaseURL: false)!
        if let skuID {
            components.queryItems = [URLQueryItem(name: "sku_id", value: skuID)]
        }
        var request = URLRequest(url: components.url!)
        request.httpMethod = "DELETE"
        return try await sendCartRequest(request)
    }

    func clear(sessionID: String) async throws -> CartState {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/cart/\(sessionID)"))
        request.httpMethod = "DELETE"
        return try await sendCartRequest(request)
    }

    func checkout(sessionID: String, address: String = "默认地址") async throws -> OrderState {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/cart/checkout"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(CheckoutRequest(sessionID: sessionID, address: address))
        let (data, response) = try await URLSession.shared.data(for: request)
        try APIClient.validate(response, data: data)
        return try decoder.decode(OrderState.self, from: data)
    }

    func createCheckoutSession(sessionID: String, address: String = "默认地址") async throws -> CheckoutSessionState {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/checkout/session"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(CreateCheckoutSessionRequest(sessionID: sessionID, userID: sessionID, address: address, paymentMode: "mock"))
        let (data, response) = try await URLSession.shared.data(for: request)
        try APIClient.validate(response, data: data)
        return try decoder.decode(CheckoutSessionState.self, from: data)
    }

    func fetchOrder(orderID: String) async throws -> OrderState {
        let url = client.baseURL.appending(path: "/api/orders/\(orderID)")
        let (data, response) = try await URLSession.shared.data(from: url)
        try APIClient.validate(response, data: data)
        return try decoder.decode(OrderState.self, from: data)
    }

    private func sendCartRequest(_ request: URLRequest) async throws -> CartState {
        let (data, response) = try await URLSession.shared.data(for: request)
        try APIClient.validate(response, data: data)
        return try decoder.decode(CartState.self, from: data)
    }
}

private struct AddCartRequest: Encodable {
    let sessionID: String
    let productID: String
    let quantity: Int
    let skuID: String?

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case productID = "product_id"
        case quantity
        case skuID = "sku_id"
    }
}

private struct UpdateCartRequest: Encodable {
    let sessionID: String
    let productID: String
    let quantity: Int
    let skuID: String?

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case productID = "product_id"
        case quantity
        case skuID = "sku_id"
    }
}

private struct CheckoutRequest: Encodable {
    let sessionID: String
    let address: String

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case address
    }
}

private struct CreateCheckoutSessionRequest: Encodable {
    let sessionID: String
    let userID: String
    let address: String
    let paymentMode: String

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case userID = "user_id"
        case address
        case paymentMode = "payment_mode"
    }
}
