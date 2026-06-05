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

    func addPreference(userID: String, text: String) async throws -> UserProfile {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/profile/\(userID)/preferences"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(AddPreferenceRequest(text: text))
        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response)
        return try decoder.decode(UserProfile.self, from: data)
    }

    func removePreference(userID: String, kind: String, value: String? = nil, key: String? = nil) async throws -> UserProfile {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/profile/\(userID)/preferences/delete"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(RemovePreferenceRequest(kind: kind, value: value, key: key))
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

private struct AddPreferenceRequest: Encodable {
    let text: String
}

private struct RemovePreferenceRequest: Encodable {
    let kind: String
    let value: String?
    let key: String?
}
