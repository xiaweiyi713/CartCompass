import Foundation

enum ChatRole: String, Hashable {
    case user
    case assistant
    case products
    case compare
    case cart
    case order
    case plan
    case weather
    case profile
    case fallback
}

struct ChatMessage: Identifiable, Hashable {
    let id: UUID
    var role: ChatRole
    var text: String
    var products: [Product]
    var comparison: ComparisonResult?
    var cart: CartState?
    var order: OrderState?
    var plan: ShoppingPlan?
    var weather: WeatherContext?
    var profile: UserProfile?
    var fallback: FallbackNotice?

    init(
        id: UUID = UUID(),
        role: ChatRole,
        text: String = "",
        products: [Product] = [],
        comparison: ComparisonResult? = nil,
        cart: CartState? = nil,
        order: OrderState? = nil,
        plan: ShoppingPlan? = nil,
        weather: WeatherContext? = nil,
        profile: UserProfile? = nil,
        fallback: FallbackNotice? = nil
    ) {
        self.id = id
        self.role = role
        self.text = text
        self.products = products
        self.comparison = comparison
        self.cart = cart
        self.order = order
        self.plan = plan
        self.weather = weather
        self.profile = profile
        self.fallback = fallback
    }
}
