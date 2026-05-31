import Foundation

struct ImageSearchService {
    private let client = APIClient()
    private let decoder = JSONDecoder()

    func search(imageData: Data, filename: String = "shopguide-upload.jpg", query: String = "") async throws -> ImageSearchResult {
        var components = URLComponents(url: client.baseURL.appending(path: "/api/image_search"), resolvingAgainstBaseURL: false)!
        if !query.isEmpty {
            components.queryItems = [URLQueryItem(name: "query", value: query)]
        }
        guard let url = components.url else {
            throw URLError(.badURL)
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = multipartBody(imageData: imageData, filename: filename, boundary: boundary)

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, 200..<300 ~= httpResponse.statusCode else {
            throw URLError(.badServerResponse)
        }
        let payload = try decoder.decode(ImageSearchResponse.self, from: data)
        return ImageSearchResult(products: payload.products, fallback: payload.fallback)
    }

    private func multipartBody(imageData: Data, filename: String, boundary: String) -> Data {
        var body = Data()
        body.append("--\(boundary)\r\n")
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n")
        body.append("Content-Type: image/jpeg\r\n\r\n")
        body.append(imageData)
        body.append("\r\n--\(boundary)--\r\n")
        return body
    }
}

private struct ImageSearchResponse: Decodable {
    let products: [Product]
    let fallback: FallbackNotice?
}

struct ImageSearchResult: Hashable {
    let products: [Product]
    let fallback: FallbackNotice?
}

private extension Data {
    mutating func append(_ string: String) {
        append(Data(string.utf8))
    }
}
