import SwiftUI

struct CompareCard: View {
    let comparison: ComparisonResult

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("商品对比", systemImage: "tablecells")
                .font(.headline)

            HStack(alignment: .top, spacing: 8) {
                Text("维度")
                    .frame(width: 68, alignment: .leading)
                    .foregroundStyle(.secondary)
                ForEach(comparison.products) { product in
                    Text(product.brand)
                        .font(.caption.weight(.semibold))
                        .lineLimit(2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            ForEach(comparison.rows) { row in
                Divider()
                HStack(alignment: .top, spacing: 8) {
                    Text(row.dimension)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .frame(width: 68, alignment: .leading)
                    ForEach(Array(row.values.enumerated()), id: \.offset) { index, value in
                        Text(value)
                            .font(.caption)
                            .lineLimit(4)
                            .padding(6)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(index == row.winner ? Color.accentColor.opacity(0.14) : Color.clear)
                            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                    }
                }
            }

            Text(comparison.summary)
                .font(.subheadline)
                .foregroundStyle(.primary)
                .padding(.top, 4)
        }
        .padding(12)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}
