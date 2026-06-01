import SwiftUI
import UIKit

struct ProductCarousel: View {
    let products: [Product]
    @Binding var path: [Product]
    let addToCart: (Product, SKU?) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Theme.Spacing.md) {
                ForEach(products) { product in
                    ProductCard(product: product) {
                        path.append(product)
                    } addToCart: {
                        if product.skus.count > 1 {
                            path.append(product)
                        } else {
                            addToCart(product, product.skus.first)
                        }
                    }
                }
            }
            .padding(.vertical, Theme.Spacing.xs)
        }
    }
}

struct ProductCard: View {
    let product: Product
    let open: () -> Void
    let addToCart: () -> Void
    private let client = APIClient()
    @State private var appeared = false

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Button(action: open) {
                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    RemoteProductImage(
                        urls: product.imageCandidates.compactMap { client.absoluteImageURL($0) },
                        contentMode: .fill
                    ) {
                        ImageSkeleton()
                    }
                    .frame(width: 220, height: 154)
                    .clipped()
                    .background(Color(.tertiarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous))

                    HStack(spacing: 6) {
                        Text(product.brand)
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(Theme.Color.quietText)
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        if product.matchScore > 0 {
                            MatchScoreBadge(score: product.matchScore, compact: true)
                        }
                    }

                    HStack(spacing: 4) {
                        Image(systemName: product.sourceURL == nil ? "archivebox" : "link")
                        Text(product.sourceName)
                            .lineLimit(1)
                    }
                    .font(.caption2)
                    .foregroundStyle(Theme.Color.quietText)

                    Text(product.title)
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(2)
                        .frame(height: 48, alignment: .topLeading)
                }
            }
            .buttonStyle(.plain)

            HStack {
                Text("¥\(product.basePrice, specifier: "%.0f")")
                    .font(.title3.weight(.bold))
                    .foregroundStyle(Theme.Color.price)
                Spacer()
                Button(action: addToCart) {
                    Image(systemName: product.skus.count > 1 ? "slider.horizontal.3" : "cart.badge.plus")
                        .font(.headline)
                        .frame(width: 38, height: 38)
                }
                .buttonStyle(.borderedProminent)
                .tint(Theme.Color.accent)
                .accessibilityLabel(product.skus.count > 1 ? "选择规格" : "加入购物车")
            }

            if let summary = summaryText {
                HStack(alignment: .top, spacing: Theme.Spacing.xs) {
                    Image(systemName: "scope")
                        .font(.caption)
                        .foregroundStyle(Theme.Color.accent)
                    Text(summary)
                        .font(.caption)
                        .foregroundStyle(Theme.Color.quietText)
                        .lineLimit(2)
                        .frame(height: 34, alignment: .topLeading)
                }
            }
        }
        .padding(Theme.Spacing.sm)
        .frame(width: 244)
        .cardSurface()
        .scaleEffect(appeared ? 1 : 0.96)
        .opacity(appeared ? 1 : 0)
        .onAppear {
            withAnimation(.snappy(duration: 0.28)) {
                appeared = true
            }
        }
    }

    private var summaryText: String? {
        if let first = product.matchReasons.first, !first.isEmpty {
            return first
        }
        if !product.reason.isEmpty {
            return product.reason
        }
        return nil
    }
}

struct MatchScoreBadge: View {
    let score: Int
    var compact = false

    var body: some View {
        Label {
            Text(compact ? "\(score)" : "匹配 \(score)")
                .font(compact ? .caption2.weight(.bold) : .footnote.weight(.semibold))
        } icon: {
            Image(systemName: "checkmark.seal.fill")
                .font(compact ? .caption2 : .footnote)
        }
        .labelStyle(.titleAndIcon)
        .foregroundStyle(.white)
        .padding(.horizontal, compact ? 7 : 10)
        .padding(.vertical, compact ? 4 : 6)
        .background(scoreColor)
        .clipShape(Capsule())
        .accessibilityLabel("匹配度 \(score)")
    }

    private var scoreColor: Color {
        if score >= 86 {
            return .green
        }
        if score >= 72 {
            return .blue
        }
        return .orange
    }
}

private struct ImageSkeleton: View {
    @State private var opacity = 0.35

    var body: some View {
        RoundedRectangle(cornerRadius: Theme.Radius.md, style: .continuous)
            .fill(Color.secondary.opacity(opacity))
            .overlay {
                Image(systemName: "photo")
                    .font(.title2)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
                    opacity = 0.16
                }
            }
    }
}

struct RemoteProductImage<Placeholder: View>: View {
    let urls: [URL]
    let contentMode: ContentMode
    @ViewBuilder let placeholder: () -> Placeholder

    @State private var image: UIImage?
    @State private var didFail = false
    @State private var loadKey = UUID()

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
            } else if didFail {
                Image(systemName: "photo")
                    .font(.largeTitle)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                placeholder()
            }
        }
        .task(id: loadKey) {
            await load()
        }
        .onChange(of: urls) { _, _ in
            image = nil
            didFail = false
            loadKey = UUID()
        }
    }

    private func load() async {
        guard image == nil, !urls.isEmpty else {
            didFail = urls.isEmpty
            return
        }
        for url in urls {
            if let cached = ProductImageMemoryCache.shared.image(for: url) {
                await MainActor.run {
                    image = cached
                    didFail = false
                }
                return
            }
            if let loaded = await fetch(url) {
                ProductImageMemoryCache.shared.set(loaded, for: url)
                await MainActor.run {
                    image = loaded
                    didFail = false
                }
                return
            }
        }
        await MainActor.run {
            didFail = true
        }
    }

    private func fetch(_ url: URL) async -> UIImage? {
        var request = URLRequest(url: url)
        request.timeoutInterval = 12
        request.cachePolicy = .returnCacheDataElseLoad
        for _ in 0..<2 {
            do {
                let (data, response) = try await URLSession.shared.data(for: request)
                guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
                    continue
                }
                if let image = UIImage(data: data) {
                    URLCache.shared.storeCachedResponse(CachedURLResponse(response: response, data: data), for: request)
                    return image
                }
            } catch {
                continue
            }
        }
        return nil
    }
}

private final class ProductImageMemoryCache {
    static let shared = ProductImageMemoryCache()
    private let cache = NSCache<NSURL, UIImage>()

    private init() {
        cache.countLimit = 200
        URLCache.shared.memoryCapacity = max(URLCache.shared.memoryCapacity, 32 * 1024 * 1024)
        URLCache.shared.diskCapacity = max(URLCache.shared.diskCapacity, 160 * 1024 * 1024)
    }

    func image(for url: URL) -> UIImage? {
        cache.object(forKey: url as NSURL)
    }

    func set(_ image: UIImage, for url: URL) {
        cache.setObject(image, forKey: url as NSURL)
    }
}
