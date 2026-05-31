import Foundation

struct APIClient {
    let baseURL = URL(string: "http://127.0.0.1:8000")!

    func absoluteImageURL(_ path: String) -> URL? {
        if path.hasPrefix("http") {
            return URL(string: path)
        }
        return URL(string: path, relativeTo: baseURL)?.absoluteURL
    }

    static func validate(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard 200..<300 ~= http.statusCode else {
            let errorResponse = try? JSONDecoder().decode(APIErrorResponse.self, from: data)
            throw RecoverableAPIError(
                statusCode: http.statusCode,
                message: errorResponse?.detail ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode),
                fallback: errorResponse?.fallback
            )
        }
    }
}

struct RecoverableAPIError: LocalizedError {
    let statusCode: Int
    let message: String
    let fallback: FallbackNotice?

    var errorDescription: String? {
        message
    }
}

private struct APIErrorResponse: Decodable {
    let detail: String?
    let fallback: FallbackNotice?
}

struct LLMAPIService {
    private let client = APIClient()
    private let decoder = JSONDecoder()

    func status(sessionID: String) async throws -> LLMStatus {
        var components = URLComponents(url: client.baseURL.appending(path: "/api/llm/status"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "session_id", value: sessionID)]
        let (data, response) = try await URLSession.shared.data(from: components.url!)
        try APIClient.validate(response, data: data)
        return try decoder.decode(LLMStatus.self, from: data)
    }

    func configure(sessionID: String, provider: String, apiKey: String, model: String, baseURL: String?) async throws -> LLMStatus {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/llm/config"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(
            LLMConfigPayload(
                sessionID: sessionID,
                provider: provider,
                model: model,
                apiKey: apiKey,
                baseURL: baseURL?.isEmpty == true ? nil : baseURL,
                temperature: 0.2,
                temporary: true
            )
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        try APIClient.validate(response, data: data)
        return try decoder.decode(LLMStatus.self, from: data)
    }

    func test(sessionID: String, provider: String, apiKey: String, model: String, baseURL: String?) async throws -> LLMTestResult {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/llm/test"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(
            LLMTestPayload(
                sessionID: sessionID,
                provider: provider,
                model: model,
                apiKey: apiKey,
                baseURL: baseURL?.isEmpty == true ? nil : baseURL,
                temperature: 0
            )
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        try APIClient.validate(response, data: data)
        return try decoder.decode(LLMTestResult.self, from: data)
    }

    func clear(sessionID: String) async throws -> LLMStatus {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/llm/config/\(sessionID)"))
        request.httpMethod = "DELETE"
        let (data, response) = try await URLSession.shared.data(for: request)
        try APIClient.validate(response, data: data)
        return try decoder.decode(LLMStatus.self, from: data)
    }
}

private struct LLMConfigPayload: Encodable {
    let sessionID: String
    let provider: String
    let model: String
    let apiKey: String
    let baseURL: String?
    let temperature: Double
    let temporary: Bool

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case provider
        case model
        case apiKey = "api_key"
        case baseURL = "base_url"
        case temperature
        case temporary
    }
}

private struct LLMTestPayload: Encodable {
    let sessionID: String
    let provider: String
    let model: String
    let apiKey: String
    let baseURL: String?
    let temperature: Double

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case provider
        case model
        case apiKey = "api_key"
        case baseURL = "base_url"
        case temperature
    }
}
