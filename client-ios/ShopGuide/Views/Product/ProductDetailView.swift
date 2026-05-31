import SwiftUI

struct ProductDetailView: View {
    let product: Product
    let addToCart: (SKU?) -> Void
    private let client = APIClient()
    @Environment(\.dismiss) private var dismiss
    @State private var selectedSKUID: String?

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
            VStack(alignment: .leading, spacing: 18) {
                RemoteProductImage(
                    urls: selectedImageCandidates.compactMap { client.absoluteImageURL($0) },
                    contentMode: .fit
                ) {
                    ProgressView()
                        .frame(maxWidth: .infinity, minHeight: 260)
                }
                .frame(maxWidth: .infinity)
                .frame(minHeight: 280)
                .background(.regularMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(Color.primary.opacity(0.06), lineWidth: 1)
                )

                VStack(alignment: .leading, spacing: 8) {
                    Text(product.brand)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text(product.title)
                        .font(.title3.weight(.semibold))
                    Text("¥\(selectedPrice, specifier: "%.0f")")
                        .font(.title2.bold())
                        .foregroundStyle(.red)
                    if let selectedSKU {
                        Text(selectedSKU.displayText)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    Text("\(product.category) / \(product.subCategory)")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    HStack(spacing: 8) {
                        Label(product.sourceName, systemImage: product.sourceURL == nil ? "archivebox" : "link")
                        if let rating = product.averageRating, product.reviewCount > 0 {
                            Label("\(rating, specifier: "%.1f") (\(product.reviewCount))", systemImage: "star.fill")
                        }
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }

                if product.matchScore > 0 || !product.matchReasons.isEmpty || !product.riskFlags.isEmpty {
                    DecisionSection(product: product)
                }

                if !product.skus.isEmpty {
                    SKUSelector(product: product, selectedSKUID: $selectedSKUID)
                }

                if !product.highlights.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("推荐要点")
                            .font(.headline)
                        ForEach(product.highlights, id: \.self) { item in
                            Label(item, systemImage: "checkmark.circle")
                                .font(.subheadline)
                                .foregroundStyle(.primary)
                        }
                    }
                }

                if !product.evidence.isEmpty || product.sourceURL != nil {
                    GroundingSection(product: product)
                }

                Button {
                    addToCart(selectedSKU)
                    dismiss()
                } label: {
                    Label("加入购物车", systemImage: "cart.badge.plus")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            .padding(16)
        }
        .background(
            LinearGradient(
                colors: [Color(.systemBackground), Color(.secondarySystemBackground)],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()
        )
        .navigationTitle("商品详情")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            selectedSKUID = selectedSKUID ?? product.skus.first?.skuID
        }
    }
}

private struct DecisionSection: View {
    let product: Product

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 10) {
                Text("推荐决策")
                    .font(.headline)
                Spacer()
                if product.matchScore > 0 {
                    MatchScoreBadge(score: product.matchScore)
                }
            }

            if !product.matchReasons.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("命中依据")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    ForEach(product.matchReasons, id: \.self) { reason in
                        Label(reason, systemImage: "scope")
                            .font(.footnote)
                            .foregroundStyle(.primary)
                            .lineLimit(2)
                    }
                }
            }

            if !product.riskFlags.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("注意点")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    ForEach(product.riskFlags, id: \.self) { flag in
                        Label(flag, systemImage: "exclamationmark.triangle")
                            .font(.footnote)
                            .foregroundStyle(.orange)
                            .lineLimit(2)
                    }
                }
            }
        }
        .padding(14)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.primary.opacity(0.06), lineWidth: 1)
        )
    }
}

private struct GroundingSection: View {
    let product: Product

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("可信依据")
                .font(.headline)
            ForEach(product.evidence, id: \.self) { item in
                Label(item, systemImage: "checkmark.seal")
                    .font(.footnote)
                    .foregroundStyle(.primary)
                    .lineLimit(3)
            }
            if let sourceURL = product.sourceURL, let url = URL(string: sourceURL) {
                Link(destination: url) {
                    Label("查看公开来源", systemImage: "safari")
                        .font(.footnote.weight(.semibold))
                }
            }
        }
        .padding(14)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.primary.opacity(0.06), lineWidth: 1)
        )
    }
}

private struct SKUSelector: View {
    let product: Product
    @Binding var selectedSKUID: String?

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
        VStack(alignment: .leading, spacing: 12) {
            Text("选择规格")
                .font(.headline)

            ForEach(propertyNames, id: \.self) { name in
                VStack(alignment: .leading, spacing: 8) {
                    Text(name)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    FlowLayout(spacing: 8) {
                        ForEach(options(for: name), id: \.self) { option in
                            let isSelected = selectedSKU?.properties[name] == option
                            Button {
                                select(name: name, option: option)
                            } label: {
                                Text(option)
                                    .font(.footnote.weight(isSelected ? .semibold : .regular))
                                    .foregroundStyle(isSelected ? .white : .primary)
                                    .padding(.horizontal, 11)
                                    .padding(.vertical, 7)
                                    .background(isSelected ? Color.accentColor : Color(.tertiarySystemGroupedBackground))
                                    .clipShape(Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
        .padding(14)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.primary.opacity(0.06), lineWidth: 1)
        )
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

private struct FlowLayout<Content: View>: View {
    let spacing: CGFloat
    @ViewBuilder let content: Content

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: spacing) {
                content
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 96), spacing: spacing)], alignment: .leading, spacing: spacing) {
                content
            }
        }
    }
}
