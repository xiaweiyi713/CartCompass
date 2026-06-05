import SwiftUI

/// Horizontally scrolling recommendation rail. Cards snap into place and rise /
/// rotate subtly with scroll position for an Apple-product-page parallax feel.
struct ProductCarousel: View {
    let products: [Product]
    @Binding var path: [Product]
    let addToCart: (Product, SKU?) -> Void

    var body: some View {
        ScrollView(.horizontal) {
            HStack(spacing: Theme.Spacing.md) {
                ForEach(products) { product in
                    ProductCard(product: product) {
                        path.append(product)
                    } addToCart: {
                        addToCart(product, product.skus.first)
                    }
                    .scrollTransition(.interactive, axis: .horizontal) { content, phase in
                        content
                            .scaleEffect(phase.isIdentity ? 1 : 0.93)
                            .opacity(phase.isIdentity ? 1 : 0.55)
                            .rotation3DEffect(.degrees(phase.value * -7), axis: (x: 0, y: 1, z: 0))
                    }
                }
            }
            .scrollTargetLayout()
            .padding(.vertical, Theme.Spacing.xxs)
        }
        .scrollTargetBehavior(.viewAligned)
        .scrollIndicators(.hidden)
    }
}

/// A single floating glass recommendation card.
struct ProductCard: View {
    let product: Product
    let open: () -> Void
    let addToCart: () -> Void

    private let client = APIClient()
    @State private var addTick = 0

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Button(action: open) { hero }
                .buttonStyle(PressableCard())

            Text(product.title)
                .font(.headline)
                .lineLimit(2)
                .frame(height: 46, alignment: .topLeading)

            if let reason = aiReason {
                Label(reason, systemImage: "sparkles")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .frame(height: 34, alignment: .topLeading)
            }

            priceRow
        }
        .padding(Theme.Spacing.sm)
        .frame(width: 250)
        .liquidGlass(radius: Theme.Radius.lg)
        .sensoryFeedback(.success, trigger: addTick)
    }

    private var hero: some View {
        RemoteProductImage(
            urls: product.imageCandidates.compactMap { client.absoluteImageURL($0) },
            contentMode: .fill
        ) {
            ImageSkeleton()
        }
        .frame(width: 226, height: 150)
        .clipped()
        .clipShape(.rect(cornerRadius: Theme.Radius.md))
        .overlay(alignment: .topTrailing) {
            if product.matchScore > 0 {
                MatchScoreBadge(score: product.matchScore, compact: true)
                    .padding(Theme.Spacing.xs)
            }
        }
        .overlay(alignment: .bottomLeading) {
            if let tag = heroBadgeText {
                ProductHeroBadge(text: tag)
                    .padding(Theme.Spacing.xs)
            }
        }
    }

    private var priceRow: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(product.basePrice, format: .currency(code: "CNY").precision(.fractionLength(0)))
                .font(.title3)
                .bold()
                .foregroundStyle(Theme.Color.price)
            Spacer()
            Button(action: handleAdd) {
                Label(addLabel, systemImage: addIcon)
                    .labelStyle(.iconOnly)
                    .font(.headline)
                    .frame(width: 44, height: 44)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Theme.Color.onAccent)
            .background(Theme.Gradient.brand, in: .circle)
            .accessibilityLabel(addLabel)
        }
    }

    private var aiReason: String? {
        if !product.reason.isEmpty { return product.reason }
        return product.matchReasons.first
    }

    private var heroBadgeText: String? {
        if let usage = usageReason {
            return usage
        }
        if let highlight = product.highlights.first {
            let trimmed = compactBadgeText(highlight)
            if !trimmed.isEmpty {
                return trimmed
            }
        }
        return product.subCategory.isEmpty ? product.category : product.subCategory
    }

    private var usageReason: String? {
        guard let range = product.reason.range(of: "用于") else { return nil }
        let usage = String(product.reason[range.lowerBound...])
        let parts = usage.split(separator: "：", maxSplits: 1).map(String.init)
        guard parts.count == 2 else { return compactBadgeText(usage) }
        let role = parts[0].replacingOccurrences(of: "用于", with: "")
        let reason = compactBadgeText(parts[1], maxLength: 14)
        if role.isEmpty { return reason }
        if reason.isEmpty { return role }
        return "\(role) · \(reason)"
    }

    private func compactBadgeText(_ text: String, maxLength: Int = 24) -> String {
        var value = text
            .replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: "  ", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        for separator in ["；", "。", ".", "|", " 规则标签", " 公开来源链接", " 原站价格"] {
            if let range = value.range(of: separator) {
                value = String(value[..<range.lowerBound]).trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
        if value.count <= maxLength { return value }
        return String(value.prefix(maxLength)).trimmingCharacters(in: .whitespacesAndNewlines) + "…"
    }

    private var addIcon: String {
        product.skus.count > 1 ? "slider.horizontal.3" : "cart.badge.plus"
    }

    private var addLabel: String {
        product.skus.count > 1 ? "选择规格" : "加入购物车"
    }

    private func handleAdd() {
        if product.skus.count > 1 {
            open()
        } else {
            addTick += 1
            addToCart()
        }
    }
}

/// Card press affordance: gentle spring scale-down, disabled under Reduce Motion.
struct PressableCard: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.97 : 1)
            .animation(Theme.Motion.spring, value: configuration.isPressed)
    }
}

/// Match-score chip. Monochrome to match the brand: a solid accent capsule with
/// inverted text keeps it high-contrast over any product photo, in both schemes.
/// The seal icon plus the score number convey confidence without relying on hue.
struct MatchScoreBadge: View {
    let score: Int
    var compact = false

    var body: some View {
        Label {
            Text(compact ? "\(score)" : "匹配 \(score)")
        } icon: {
            Image(systemName: "checkmark.seal.fill")
        }
        .font(compact ? .caption.bold() : .footnote.weight(.semibold))
        .foregroundStyle(Theme.Color.onAccent)
        .padding(.horizontal, compact ? 8 : 10)
        .padding(.vertical, compact ? 5 : 6)
        .background(Theme.Color.accent.gradient, in: .capsule)
        .overlay(Capsule().strokeBorder(Theme.Color.glassHighlight, lineWidth: 0.6))
        .accessibilityLabel("匹配度 \(score) 分")
    }
}

private struct ProductHeroBadge: View {
    let text: String

    var body: some View {
        Label(text, systemImage: "checkmark.seal.fill")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(Theme.Color.accent)
            .lineLimit(2)
            .multilineTextAlignment(.leading)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .frame(maxWidth: 168, alignment: .leading)
            .background(.ultraThinMaterial, in: .rect(cornerRadius: 16, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(Theme.Color.accent.opacity(0.26), lineWidth: 0.8)
            )
            .accessibilityLabel(text)
    }
}

// MARK: - Remote image with shimmer placeholder + in-memory cache

/// Loads a product image, trying candidate URLs in order. Shows a shimmering
/// glass placeholder while loading and falls back to a symbol on failure.
struct RemoteProductImage<Placeholder: View>: View {
    let urls: [URL]
    let contentMode: ContentMode
    @ViewBuilder let placeholder: Placeholder

    @State private var image: UIImage?
    @State private var didFail = false

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
            } else if didFail {
                Image(systemName: "photo")
                    .font(.largeTitle)
                    .foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                placeholder
            }
        }
        .task(id: urls) {
            await load()
        }
    }

    private func load() async {
        image = nil
        didFail = false
        guard !urls.isEmpty else {
            didFail = true
            return
        }
        for url in urls {
            if let cached = ProductImageMemoryCache.shared.image(for: url) {
                image = cached
                return
            }
            if let loaded = await fetch(url) {
                ProductImageMemoryCache.shared.set(loaded, for: url)
                image = loaded
                return
            }
        }
        didFail = true
    }

    private func fetch(_ url: URL) async -> UIImage? {
        var request = URLRequest(url: url)
        request.timeoutInterval = 12
        request.cachePolicy = .returnCacheDataElseLoad
        for _ in 0..<2 {
            do {
                let (data, response) = try await URLSession.shared.data(for: request)
                guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else { continue }
                if let image = UIImage(data: data) { return image }
            } catch {
                continue
            }
        }
        return nil
    }
}

/// Glassy shimmer placeholder shown while a product image loads.
struct ImageSkeleton: View {
    var body: some View {
        Rectangle()
            .fill(.ultraThinMaterial)
            .overlay {
                PhaseAnimator([0.25, 0.6]) { opacity in
                    Image(systemName: "photo")
                        .font(.title2)
                        .foregroundStyle(.tertiary)
                        .opacity(opacity)
                } animation: { _ in .easeInOut(duration: 0.9) }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

final class ProductImageMemoryCache {
    static let shared = ProductImageMemoryCache()
    private let cache = NSCache<NSURL, UIImage>()

    private init() {
        cache.countLimit = 200
    }

    func image(for url: URL) -> UIImage? {
        cache.object(forKey: url as NSURL)
    }

    func set(_ image: UIImage, for url: URL) {
        cache.setObject(image, forKey: url as NSURL)
    }
}
