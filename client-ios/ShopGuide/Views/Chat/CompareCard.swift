import SwiftUI

/// Side-by-side product comparison for the "compare first two" flow.
///
/// The chat surface is narrow, so this intentionally avoids a horizontally
/// scrolling matrix. Each comparison dimension owns its own two-column row,
/// which keeps long values readable without pushing other cells off-screen.
struct CompareCard: View {
    let comparison: ComparisonResult

    private var products: [Product] {
        Array(comparison.products.prefix(2))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Label("商品对比", systemImage: "square.split.2x2")
                .font(.headline)

            if products.count == 2 {
                HStack(alignment: .top, spacing: Theme.Spacing.sm) {
                    ForEach(products) { product in
                        CompareProductHeader(product: product)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }

                VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
                    ForEach(comparison.rows) { row in
                        CompareDimensionRow(row: row, productCount: products.count)
                    }
                }
            } else {
                Text("还需要两款商品才能生成完整对比。")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            Label(comparison.summary, systemImage: "sparkles")
                .font(.subheadline)
                .padding(.top, Theme.Spacing.xxs)
        }
        .padding(Theme.Spacing.md)
        .liquidGlass(radius: Theme.Radius.lg)
    }
}

/// Product header with image, brand and a short title cue.
private struct CompareProductHeader: View {
    let product: Product
    private let client = APIClient()

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xxs) {
            RemoteProductImage(
                urls: product.imageCandidates.compactMap { client.absoluteImageURL($0) },
                contentMode: .fill
            ) {
                ImageSkeleton()
            }
            .frame(height: 86)
            .clipped()
            .clipShape(.rect(cornerRadius: Theme.Radius.sm))

            Text(product.brand)
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)

            Text(product.title)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
    }
}

/// One comparison dimension rendered as a stable two-column row.
private struct CompareDimensionRow: View {
    let row: ComparisonRow
    let productCount: Int

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            Text(row.dimension)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            HStack(alignment: .top, spacing: Theme.Spacing.sm) {
                ForEach(0..<productCount, id: \.self) { index in
                    CompareValueCard(
                        value: value(at: index),
                        isWinner: row.winner == index
                    )
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                }
            }
        }
        .padding(.top, Theme.Spacing.xs)
        .overlay(alignment: .top) {
            Divider()
        }
    }

    private func value(at index: Int) -> String {
        guard row.values.indices.contains(index) else { return "暂无数据" }
        return row.values[index]
    }
}

/// A single comparison value cell, highlighted when it wins its row.
private struct CompareValueCard: View {
    let value: String
    let isWinner: Bool

    var body: some View {
        HStack(alignment: .top, spacing: Theme.Spacing.xxs) {
            if isWinner {
                Image(systemName: "trophy.fill")
                    .font(.caption2)
                    .foregroundStyle(Theme.Color.accent)
            }
            Text(value)
                .font(.caption)
                .foregroundStyle(isWinner ? .primary : .secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Theme.Spacing.xs)
        .background {
            if isWinner {
                RoundedRectangle(cornerRadius: Theme.Radius.sm)
                    .fill(Theme.Color.accent.opacity(0.16))
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.Radius.sm)
                            .strokeBorder(Theme.Color.accent.opacity(0.4), lineWidth: 0.8)
                    )
            }
        }
    }
}
