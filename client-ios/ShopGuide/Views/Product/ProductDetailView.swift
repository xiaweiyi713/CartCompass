import SwiftUI

/// Immersive product detail screen: a parallax glass header, highlighted specs,
/// a grounded review visualization, SKU selection, and a sticky glass buy bar.
/// View layer only — `addToCart` is supplied by the caller's view model.
struct ProductDetailView: View {
    let product: Product
    let addToCart: (SKU?) -> Void

    private let client = APIClient()
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var selectedSKUID: String?
    @State private var addTick = 0

    private var selectedSKU: SKU? {
        if let selectedSKUID, let sku = product.skus.first(where: { $0.skuID == selectedSKUID }) {
            return sku
        }
        return product.skus.first
    }

    private var selectedImageCandidates: [String] {
        var candidates = product.imageCandidates
        if let imageURL = selectedSKU?.imageURL, !imageURL.isEmpty {
            candidates.removeAll { $0 == imageURL }
            candidates.insert(imageURL, at: 0)
        }
        return candidates
    }

    private var selectedPrice: Double {
        selectedSKU?.price ?? product.basePrice
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                parallaxHeader
                ProductHeadline(product: product, sku: selectedSKU, price: selectedPrice)

                if !product.highlights.isEmpty {
                    SpecHighlights(highlights: product.highlights)
                }

                ReviewSummarySection(product: product)

                if !product.skus.isEmpty {
                    SKUSelector(product: product, selectedSKUID: $selectedSKUID)
                }

                if product.matchScore > 0 || !product.matchReasons.isEmpty || !product.riskFlags.isEmpty {
                    DecisionSection(product: product)
                }

                if !product.evidence.isEmpty || product.sourceURL != nil {
                    GroundingSection(product: product)
                }
            }
            .padding(.horizontal, Theme.Spacing.md)
            .padding(.bottom, Theme.Spacing.xl)
        }
        .scrollIndicators(.hidden)
        .background(LiquidBackdrop())
        .navigationTitle("商品详情")
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom) { buyBar }
        .onAppear { selectedSKUID = selectedSKUID ?? product.skus.first?.skuID }
    }

    private var parallaxHeader: some View {
        // Capture a Sendable copy: visualEffect's closure is @Sendable and this
        // view is not Sendable (it stores a non-Sendable addToCart closure).
        let motionEnabled = !reduceMotion
        return RemoteProductImage(
            urls: selectedImageCandidates.compactMap { client.absoluteImageURL($0) },
            contentMode: .fill
        ) {
            ImageSkeleton()
        }
        .frame(maxWidth: .infinity)
        .frame(height: 300)
        .clipShape(.rect(cornerRadius: Theme.Radius.lg))
        .liquidGlass(radius: Theme.Radius.lg)
        .visualEffect { content, proxy in
            let stretch = motionEnabled ? max(0, proxy.frame(in: .scrollView).minY) : 0
            return content
                .scaleEffect(1 + stretch / 700, anchor: .top)
                .offset(y: -stretch * 0.25)
        }
    }

    private var buyBar: some View {
        HStack(spacing: Theme.Spacing.md) {
            VStack(alignment: .leading, spacing: 0) {
                Text("到手价")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(selectedPrice, format: .currency(code: "CNY").precision(.fractionLength(0)))
                    .font(.title3)
                    .bold()
                    .foregroundStyle(Theme.Color.price)
                    .contentTransition(.numericText())
                    .animation(Theme.Motion.snappy, value: selectedPrice)
            }

            Button(action: handleAdd) {
                Label("加入购物车", systemImage: "cart.badge.plus")
                    .font(.headline.weight(.bold))
                    .foregroundStyle(.black)
                    .symbolRenderingMode(.hierarchical)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .background(Color.white.opacity(0.96), in: .capsule)
                    .overlay(Capsule().strokeBorder(Color.white.opacity(0.35), lineWidth: 1))
                    .shadow(color: .black.opacity(0.28), radius: 18, y: 8)
            }
            .buttonStyle(ProductDetailPressButtonStyle())
        }
        .padding(Theme.Spacing.md)
        .background(.bar)
        .sensoryFeedback(.success, trigger: addTick)
    }

    private func handleAdd() {
        addTick += 1
        addToCart(selectedSKU)
        dismiss()
    }
}

/// Brand, title, rating, and category line.
private struct ProductHeadline: View {
    let product: Product
    let sku: SKU?
    let price: Double

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text(product.brand)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text(product.title)
                .font(.title2)
                .bold()
            if let sku {
                Text(sku.displayText)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: Theme.Spacing.sm) {
                Label(product.sourceName, systemImage: product.sourceURL == nil ? "archivebox" : "link")
                if let rating = product.averageRating, product.reviewCount > 0 {
                    Label("\(rating, format: .number.precision(.fractionLength(1)))", systemImage: "star.fill")
                        .foregroundStyle(.primary)
                }
                Text("\(product.category) · \(product.subCategory)")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
    }
}

/// Key specs surfaced as prominent glass chips.
private struct SpecHighlights: View {
    let highlights: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Text("关键亮点")
                .font(.headline)
            VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                ForEach(highlights, id: \.self) { item in
                    ReviewTag(text: item, systemImage: "sparkle", tint: .primary)
                }
            }
        }
    }
}

/// Grounded review visualization: a rating dial plus tag clouds drawn from the
/// product's real highlight / risk / evidence fields. No fabricated star
/// distribution — only signals that actually exist in the catalog are shown.
private struct ReviewSummarySection: View {
    let product: Product

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            Text("用户评价")
                .font(.headline)

            VStack(alignment: .leading, spacing: Theme.Spacing.md) {
                RatingDial(rating: product.averageRating, count: product.reviewCount)
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    if !product.highlights.isEmpty {
                        Text("好评关键词")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                            ForEach(product.highlights, id: \.self) { tag in
                                ReviewTag(text: tag, tint: Theme.Color.accent)
                            }
                        }
                    }
                    if !product.riskFlags.isEmpty {
                        Text("需要注意")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .padding(.top, Theme.Spacing.xxs)
                        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                            ForEach(product.riskFlags, id: \.self) { tag in
                                ReviewTag(text: tag, systemImage: "exclamationmark.triangle.fill", tint: .secondary)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(Theme.Spacing.md)
        .liquidGlass(radius: Theme.Radius.md)
    }
}

/// Circular rating indicator. Falls back to a neutral state when no rating
/// exists, rather than inventing one.
private struct RatingDial: View {
    let rating: Double?
    let count: Int

    private var fraction: Double { (rating ?? 0) / 5 }

    var body: some View {
        ZStack {
            Circle()
                .stroke(.quaternary, lineWidth: 8)
            Circle()
                .trim(from: 0, to: fraction)
                .stroke(Theme.Gradient.brand, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                .rotationEffect(.degrees(-90))
            VStack(spacing: 0) {
                if let rating {
                    Text(rating, format: .number.precision(.fractionLength(1)))
                        .font(.title2)
                        .bold()
                    Text("\(count) 条")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Text("暂无")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(width: 88, height: 88)
        .accessibilityElement()
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        guard let rating else { return "暂无评分" }
        let score = rating.formatted(.number.precision(.fractionLength(1)))
        return "评分 \(score) 分，共 \(count) 条评价"
    }
}

private struct ReviewTag: View {
    let text: String
    var systemImage: String?
    var tint: Color = Theme.Color.accent

    var body: some View {
        label
            .font(.caption.weight(.semibold))
            .lineLimit(2)
            .fixedSize(horizontal: false, vertical: true)
            .foregroundStyle(tint)
            .padding(.horizontal, Theme.Spacing.sm)
            .padding(.vertical, Theme.Spacing.xxs + 2)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                RoundedRectangle(cornerRadius: Theme.Radius.sm, style: .continuous).fill(.ultraThinMaterial)
                RoundedRectangle(cornerRadius: Theme.Radius.sm, style: .continuous).fill(tint.opacity(0.14))
                RoundedRectangle(cornerRadius: Theme.Radius.sm, style: .continuous)
                    .strokeBorder(tint.opacity(0.32), lineWidth: 0.8)
            }
    }

    @ViewBuilder private var label: some View {
        if let systemImage {
            Label(text, systemImage: systemImage)
        } else {
            Text(text)
        }
    }
}

private struct ProductDetailPressButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.88 : 1)
            .animation(Theme.Motion.spring, value: configuration.isPressed)
    }
}

/// SKU option picker. The selected option's accent pill slides between choices
/// with `matchedGeometryEffect`.
private struct SKUSelector: View {
    let product: Product
    @Binding var selectedSKUID: String?
    @Namespace private var pill

    private var selectedSKU: SKU? {
        if let selectedSKUID, let sku = product.skus.first(where: { $0.skuID == selectedSKUID }) {
            return sku
        }
        return product.skus.first
    }

    private var propertyNames: [String] {
        let preferred = ["颜色", "存储", "版本", "规格", "尺码"]
        let names = Set(product.skus.flatMap { $0.properties.keys })
        return names.sorted { left, right in
            (preferred.firstIndex(of: left) ?? 99, left) < (preferred.firstIndex(of: right) ?? 99, right)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.md) {
            Text("选择规格")
                .font(.headline)
            ForEach(propertyNames, id: \.self) { name in
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text(name)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    FlowLayout(spacing: Theme.Spacing.xs) {
                        ForEach(options(for: name), id: \.self) { option in
                            optionChip(name: name, option: option)
                        }
                    }
                }
            }
        }
        .padding(Theme.Spacing.md)
        .liquidGlass(radius: Theme.Radius.md)
    }

    private func optionChip(name: String, option: String) -> some View {
        let isSelected = selectedSKU?.properties[name] == option
        return Button {
            withAnimation(Theme.Motion.spring) { select(name: name, option: option) }
        } label: {
            Text(option)
                .font(.footnote.weight(isSelected ? .semibold : .regular))
                .foregroundStyle(isSelected ? Theme.Color.onAccent : .primary)
                .padding(.horizontal, Theme.Spacing.sm)
                .padding(.vertical, Theme.Spacing.xs)
                .frame(minHeight: 44)
                .background {
                    if isSelected {
                        Capsule().fill(Theme.Gradient.brand)
                            .matchedGeometryEffect(id: "skuPill-\(name)", in: pill)
                    } else {
                        Capsule().fill(.ultraThinMaterial)
                    }
                }
        }
        .buttonStyle(.plain)
    }

    private func options(for name: String) -> [String] {
        Array(Set(product.skus.compactMap { $0.properties[name] })).sorted()
    }

    private func select(name: String, option: String) {
        var target = selectedSKU?.properties ?? [:]
        target[name] = option
        if let exact = product.skus.first(where: { sku in
            target.allSatisfy { key, value in sku.properties[key] == value }
        }) {
            selectedSKUID = exact.skuID
            return
        }
        selectedSKUID = product.skus.first(where: { $0.properties[name] == option })?.skuID
    }
}

/// Why this product was recommended, plus any caution flags.
private struct DecisionSection: View {
    let product: Product

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            HStack {
                Text("推荐决策")
                    .font(.headline)
                Spacer()
                if product.matchScore > 0 {
                    MatchScoreBadge(score: product.matchScore)
                }
            }
            if !product.matchReasons.isEmpty {
                ForEach(product.matchReasons, id: \.self) { reason in
                    Label(reason, systemImage: "scope")
                        .font(.footnote)
                        .lineLimit(2)
                }
            }
            if !product.riskFlags.isEmpty {
                ForEach(product.riskFlags, id: \.self) { flag in
                    Label(flag, systemImage: "exclamationmark.triangle")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        }
        .padding(Theme.Spacing.md)
        .liquidGlass(radius: Theme.Radius.md)
    }
}

/// Verifiable evidence and the public source link backing the recommendation.
private struct GroundingSection: View {
    let product: Product

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Text("可信依据")
                .font(.headline)
            ForEach(product.evidence, id: \.self) { item in
                Label(item, systemImage: "checkmark.seal")
                    .font(.footnote)
                    .lineLimit(3)
            }
            if let sourceURL = product.sourceURL, let url = URL(string: sourceURL) {
                Link(destination: url) {
                    Label("查看公开来源", systemImage: "safari")
                        .font(.footnote.weight(.semibold))
                }
            }
        }
        .padding(Theme.Spacing.md)
        .liquidGlass(radius: Theme.Radius.md)
    }
}

/// Wrapping chip layout built on the `Layout` protocol — used by spec
/// highlights, tag clouds, and SKU options.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Void) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        let rows = arrange(subviews, maxWidth: maxWidth)
        let width = rows.map(\.width).max() ?? 0
        let height = rows.map(\.height).reduce(0, +) + spacing * CGFloat(max(0, rows.count - 1))
        return CGSize(width: min(width, maxWidth), height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Void) {
        let rows = arrange(subviews, maxWidth: bounds.width)
        var y = bounds.minY
        for row in rows {
            var x = bounds.minX
            for index in row.indices {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row {
        var indices: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func arrange(_ subviews: Subviews, maxWidth: CGFloat) -> [Row] {
        var rows: [Row] = []
        var current = Row()
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let projected = current.width == 0 ? size.width : current.width + spacing + size.width
            if projected > maxWidth, !current.indices.isEmpty {
                rows.append(current)
                current = Row()
            }
            current.width = current.width == 0 ? size.width : current.width + spacing + size.width
            current.height = max(current.height, size.height)
            current.indices.append(index)
        }
        if !current.indices.isEmpty { rows.append(current) }
        return rows
    }
}
