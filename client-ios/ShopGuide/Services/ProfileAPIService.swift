import Foundation

struct ProfileAPIService {
    private let client = APIClient()
    private let decoder = JSONDecoder()

    func fetch(sessionID: String) async throws -> UserProfile {
        let url = client.baseURL.appending(path: "/api/profile/\(sessionID)")
        let (data, response) = try await URLSession.shared.data(from: url)
        try validate(response)
        return try decoder.decode(UserProfile.self, from: data)
    }

    func clear(sessionID: String) async throws -> UserProfile {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/profile/\(sessionID)"))
        request.httpMethod = "DELETE"
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response)
        return try decoder.decode(UserProfile.self, from: data)
    }

    private func validate(_ response: URLResponse) throws {
        guard let httpResponse = response as? HTTPURLResponse, 200..<300 ~= httpResponse.statusCode else {
            throw URLError(.badServerResponse)
        }
    }
}
