import Foundation

struct SKU: Codable, Hashable, Identifiable {
    var id: String { skuID }
    let skuID: String
    let properties: [String: String]
    let price: Double
    let imageURL: String?

    enum CodingKeys: String, CodingKey {
        case skuID = "sku_id"
        case properties
        case price
        case imageURL = "image_url"
    }

    var displayText: String {
        properties
            .sorted { left, right in
                SKU.propertyOrder(left.key) < SKU.propertyOrder(right.key)
            }
            .map(\.value)
            .joined(separator: " / ")
    }

    private static func propertyOrder(_ key: String) -> Int {
        ["颜色", "存储", "版本", "规格", "尺码"].firstIndex(of: key) ?? 99
    }
}

struct Product: Codable, Hashable, Identifiable {
    var id: String { productID }
    let productID: String
    let title: String
    let brand: String
    let category: String
    let subCategory: String
    let basePrice: Double
    let imageURL: String
    let stockStatus: String
    let inventoryCount: Int
    let skus: [SKU]
    let highlights: [String]
    let reason: String
    let sourceURL: String?
    let sourceName: String
    let evidence: [String]
    let averageRating: Double?
    let reviewCount: Int
    let matchScore: Int
    let matchReasons: [String]
    let riskFlags: [String]

    var imageCandidates: [String] {
        var seen = Set<String>()
        return ([imageURL] + skus.compactMap(\.imageURL))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .filter { seen.insert($0).inserted }
    }

    enum CodingKeys: String, CodingKey {
        case productID = "product_id"
        case title
        case brand
        case category
        case subCategory = "sub_category"
        case basePrice = "base_price"
        case imageURL = "image_url"
        case stockStatus = "stock_status"
        case inventoryCount = "inventory_count"
        case skus
        case highlights
        case reason
        case sourceURL = "source_url"
        case sourceName = "source_name"
        case evidence
        case averageRating = "average_rating"
        case reviewCount = "review_count"
        case matchScore = "match_score"
        case matchReasons = "match_reasons"
        case riskFlags = "risk_flags"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        productID = try container.decode(String.self, forKey: .productID)
        title = try container.decode(String.self, forKey: .title)
        brand = try container.decode(String.self, forKey: .brand)
        category = try container.decode(String.self, forKey: .category)
        subCategory = try container.decode(String.self, forKey: .subCategory)
        basePrice = try container.decode(Double.self, forKey: .basePrice)
        imageURL = try container.decode(String.self, forKey: .imageURL)
        stockStatus = try container.decodeIfPresent(String.self, forKey: .stockStatus) ?? "in_stock"
        inventoryCount = try container.decodeIfPresent(Int.self, forKey: .inventoryCount) ?? 8
        skus = try container.decodeIfPresent([SKU].self, forKey: .skus) ?? []
        highlights = try container.decodeIfPresent([String].self, forKey: .highlights) ?? []
        reason = try container.decodeIfPresent(String.self, forKey: .reason) ?? ""
        sourceURL = try container.decodeIfPresent(String.self, forKey: .sourceURL)
        sourceName = try container.decodeIfPresent(String.self, forKey: .sourceName) ?? "赛题示例商品库"
        evidence = try container.decodeIfPresent([String].self, forKey: .evidence) ?? []
        averageRating = try container.decodeIfPresent(Double.self, forKey: .averageRating)
        reviewCount = try container.decodeIfPresent(Int.self, forKey: .reviewCount) ?? 0
        matchScore = try container.decodeIfPresent(Int.self, forKey: .matchScore) ?? 0
        matchReasons = try container.decodeIfPresent([String].self, forKey: .matchReasons) ?? []
        riskFlags = try container.decodeIfPresent([String].self, forKey: .riskFlags) ?? []
    }
}

struct CartItem: Codable, Hashable, Identifiable {
    var id: String { lineID }
    let lineID: String
    let product: Product
    let quantity: Int
    let selectedSKU: SKU?
    let unitPrice: Double

    enum CodingKeys: String, CodingKey {
        case lineID = "line_id"
        case product
        case quantity
        case selectedSKU = "selected_sku"
        case unitPrice = "unit_price"
    }
}

struct WeatherLocation: Codable, Hashable {
    let name: String
    let country: String?
    let latitude: Double
    let longitude: Double
    let timezone: String?
}

struct CurrentWeather: Codable, Hashable {
    let temperatureC: Double?
    let apparentTemperatureC: Double?
    let condition: String
    let precipitationMM: Double?
    let rainProbability: Double?
    let humidity: Double?
    let windSpeedKMH: Double?
    let uvIndex: Double?
    let isDay: Bool?

    enum CodingKeys: String, CodingKey {
        case temperatureC = "temperature_c"
        case apparentTemperatureC = "apparent_temperature_c"
        case condition
        case precipitationMM = "precipitation_mm"
        case rainProbability = "rain_probability"
        case humidity
        case windSpeedKMH = "wind_speed_kmh"
        case uvIndex = "uv_index"
        case isDay = "is_day"
    }
}

struct DailyWeather: Codable, Hashable, Identifiable {
    var id: String { date }
    let date: String
    let tempMinC: Double?
    let tempMaxC: Double?
    let precipitationProbabilityMax: Double?
    let uvIndexMax: Double?
    let condition: String?

    enum CodingKeys: String, CodingKey {
        case date
        case tempMinC = "temp_min_c"
        case tempMaxC = "temp_max_c"
        case precipitationProbabilityMax = "precipitation_probability_max"
        case uvIndexMax = "uv_index_max"
        case condition
    }
}

struct WeatherImplications: Codable, Hashable {
    let tags: [String]
    let shoppingNeeds: [String]
    let travelAdvice: [String]

    enum CodingKeys: String, CodingKey {
        case tags
        case shoppingNeeds = "shopping_needs"
        case travelAdvice = "travel_advice"
    }
}

struct WeatherContext: Codable, Hashable {
    let location: WeatherLocation
    let current: CurrentWeather?
    let daily: [DailyWeather]
    let implications: WeatherImplications
    let source: String
    let fetchedAt: String

    enum CodingKeys: String, CodingKey {
        case location
        case current
        case daily
        case implications
        case source
        case fetchedAt = "fetched_at"
    }
}

struct CartState: Codable, Hashable {
    let sessionID: String
    let items: [CartItem]
    let totalPrice: Double

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case items
        case totalPrice = "total_price"
    }
}

struct OrderItem: Codable, Hashable, Identifiable {
    var id: String { skuID.map { "\(productID)::\($0)" } ?? productID }
    let productID: String
    let title: String
    let unitPrice: Double
    let quantity: Int
    let subtotal: Double
    let skuID: String?
    let skuText: String?

    enum CodingKeys: String, CodingKey {
        case productID = "product_id"
        case title
        case unitPrice = "unit_price"
        case quantity
        case subtotal
        case skuID = "sku_id"
        case skuText = "sku_text"
    }
}

struct OrderState: Codable, Hashable, Identifiable {
    var id: String { orderID }
    let orderID: String
    let sessionID: String
    let address: String
    let items: [OrderItem]
    let totalPrice: Double
    let status: String
    let paymentStatus: String
    let paymentProvider: String
    let checkoutSessionID: String?
    let paidAt: String?
    let postPurchaseRecommendations: [Product]

    enum CodingKeys: String, CodingKey {
        case orderID = "order_id"
        case sessionID = "session_id"
        case address
        case items
        case totalPrice = "total_price"
        case status
        case paymentStatus = "payment_status"
        case paymentProvider = "payment_provider"
        case checkoutSessionID = "checkout_session_id"
        case paidAt = "paid_at"
        case postPurchaseRecommendations = "post_purchase_recommendations"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        orderID = try container.decode(String.self, forKey: .orderID)
        sessionID = try container.decode(String.self, forKey: .sessionID)
        address = try container.decode(String.self, forKey: .address)
        items = try container.decode([OrderItem].self, forKey: .items)
        totalPrice = try container.decode(Double.self, forKey: .totalPrice)
        status = try container.decodeIfPresent(String.self, forKey: .status) ?? "created"
        paymentStatus = try container.decodeIfPresent(String.self, forKey: .paymentStatus) ?? "UNPAID"
        paymentProvider = try container.decodeIfPresent(String.self, forKey: .paymentProvider) ?? "mock"
        checkoutSessionID = try container.decodeIfPresent(String.self, forKey: .checkoutSessionID)
        paidAt = try container.decodeIfPresent(String.self, forKey: .paidAt)
        postPurchaseRecommendations = try container.decodeIfPresent([Product].self, forKey: .postPurchaseRecommendations) ?? []
    }
}

struct CheckoutSessionState: Codable, Hashable, Identifiable {
    var id: String { checkoutSessionID }
    let checkoutSessionID: String
    let checkoutURL: String
    let expiresAt: String
    let status: String
    let totalAmount: Double
    let currency: String
    let review: [String]

    enum CodingKeys: String, CodingKey {
        case checkoutSessionID = "checkout_session_id"
        case checkoutURL = "checkout_url"
        case expiresAt = "expires_at"
        case status
        case totalAmount = "total_amount"
        case currency
        case review
    }
}

struct ComparisonResult: Codable, Hashable {
    let products: [Product]
    let rows: [ComparisonRow]
    let summary: String
}

struct ComparisonRow: Codable, Hashable, Identifiable {
    var id: String { dimension }
    let dimension: String
    let values: [String]
    let winner: Int?
}

struct ShoppingPlan: Codable, Hashable, Identifiable {
    var id: String { title }
    let title: String
    let budget: Double
    let totalPrice: Double
    let remainingBudget: Double
    let items: [ShoppingPlanItem]
    let upgradeOptions: [ShoppingPlanItem]
    let notes: [String]

    enum CodingKeys: String, CodingKey {
        case title
        case budget
        case totalPrice = "total_price"
        case remainingBudget = "remaining_budget"
        case items
        case upgradeOptions = "upgrade_options"
        case notes
    }
}

struct ShoppingPlanItem: Codable, Hashable, Identifiable {
    var id: String { "\(role)-\(product.productID)" }
    let role: String
    let product: Product
    let reason: String
    let optional: Bool
}

struct UserProfile: Codable, Hashable {
    let userID: String
    let budgetPreferences: [String: Double]
    let preferredFeatures: [String]
    let excludedBrands: [String]
    let excludedIngredients: [String]
    let skinType: String?
    let travelScenario: [String]
    let lastFeedback: [[String: String]]

    enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case budgetPreferences = "budget_preferences"
        case preferredFeatures = "preferred_features"
        case excludedBrands = "excluded_brands"
        case excludedIngredients = "excluded_ingredients"
        case skinType = "skin_type"
        case travelScenario = "travel_scenario"
        case lastFeedback = "last_feedback"
    }

    static let empty = UserProfile(
        userID: "ios-demo",
        budgetPreferences: [:],
        preferredFeatures: [],
        excludedBrands: [],
        excludedIngredients: [],
        skinType: nil,
        travelScenario: [],
        lastFeedback: []
    )

    var isEmpty: Bool {
        budgetPreferences.isEmpty
            && preferredFeatures.isEmpty
            && excludedBrands.isEmpty
            && excludedIngredients.isEmpty
            && skinType == nil
            && travelScenario.isEmpty
    }
}

struct LLMStatus: Codable, Hashable {
    let configured: Bool
    let provider: String
    let model: String?
    let baseURL: String?
    let source: String
    let keyPresent: Bool
    let keyHint: String?

    enum CodingKeys: String, CodingKey {
        case configured
        case provider
        case model
        case baseURL = "base_url"
        case source
        case keyPresent = "key_present"
        case keyHint = "key_hint"
    }

    static let empty = LLMStatus(
        configured: false,
        provider: "disabled",
        model: nil,
        baseURL: nil,
        source: "fallback",
        keyPresent: false,
        keyHint: nil
    )
}

struct LLMTestResult: Codable, Hashable {
    let ok: Bool
    let provider: String
    let model: String?
    let latencyMS: Double
    let message: String
    let fallback: FallbackNotice?

    enum CodingKeys: String, CodingKey {
        case ok
        case provider
        case model
        case latencyMS = "latency_ms"
        case message
        case fallback
    }
}

struct RecoveryAction: Codable, Hashable, Identifiable {
    var id: String { "\(label)-\(prompt)" }
    let label: String
    let prompt: String
}

struct FallbackNotice: Codable, Hashable {
    let code: String
    let title: String
    let message: String
    let actions: [RecoveryAction]
    let severity: String

    init(
        code: String = "general",
        title: String,
        message: String,
        actions: [RecoveryAction] = [],
        severity: String = "info"
    ) {
        self.code = code
        self.title = title
        self.message = message
        self.actions = actions
        self.severity = severity
    }
}
