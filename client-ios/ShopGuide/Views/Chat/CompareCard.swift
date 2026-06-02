import SwiftUI

/// Side-by-side product comparison. A `Grid` keeps columns aligned; the whole
/// matrix scrolls horizontally so 2-3 products with long values stay readable.
/// The winning cell in each row is highlighted with an accent glass fill plus a
/// trophy icon (so it reads without relying on color alone).
struct CompareCard: View {
    let comparison: ComparisonResult

    private let labelWidth: CGFloat = 64
    private let columnWidth: CGFloat = 150

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.sm) {
            Label("商品对比", systemImage: "square.split.2x2")
                .font(.headline)

            ScrollView(.horizontal) {
                Grid(alignment: .topLeading,
                     horizontalSpacing: Theme.Spacing.sm,
                     verticalSpacing: Theme.Spacing.sm) {
                    GridRow {
                        Color.clear.frame(width: labelWidth, height: 1)
                        ForEach(comparison.products) { product in
                            CompareColumnHeader(product: product)
                                .frame(width: columnWidth, alignment: .leading)
                        }
                    }

                    ForEach(comparison.rows) { row in
                        Divider().gridCellColumns(comparison.products.count + 1)
                        GridRow {
                            Text(row.dimension)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .frame(width: labelWidth, alignment: .leading)
                            ForEach(Array(row.values.enumerated()), id: \.offset) { index, value in
                                CompareCell(value: value, isWinner: index == row.winner)
                                    .frame(width: columnWidth, alignment: .leading)
                            }
                        }
                    }
                }
            }
            .scrollIndicators(.hidden)

            Label(comparison.summary, systemImage: "sparkles")
                .font(.subheadline)
                .padding(.top, Theme.Spacing.xxs)
        }
        .padding(Theme.Spacing.md)
        .liquidGlass(radius: Theme.Radius.lg)
    }
}

/// Product column header: thumbnail + brand, kept compact for the matrix.
private struct CompareColumnHeader: View {
    let product: Product
    private let client = APIClient()

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
            RemoteProductImage(
                urls: product.imageCandidates.compactMap { client.absoluteImageURL($0) },
                contentMode: .fill
            ) {
                ImageSkeleton()
            }
            .frame(width: 150, height: 90)
            .clipped()
            .clipShape(.rect(cornerRadius: Theme.Radius.sm))

            Text(product.brand)
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)
        }
    }
}

/// A single comparison value cell, highlighted when it wins its row.
private struct CompareCell: View {
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
