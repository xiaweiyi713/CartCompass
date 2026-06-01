import SwiftUI

struct ShoppingPlanCard: View {
    let plan: ShoppingPlan
    @Binding var path: [Product]
    let addToCart: (Product, SKU?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Label(plan.title, systemImage: "checklist.checked")
                        .font(.headline)
                    Text("总价 ¥\(plan.totalPrice, specifier: "%.0f") / 预算 ¥\(plan.budget, specifier: "%.0f")")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                BudgetPill(value: plan.remainingBudget)
            }

            VStack(spacing: 10) {
                ForEach(plan.items) { item in
                    PlanItemRow(item: item, path: $path, addToCart: addToCart)
                }
            }

            if !plan.upgradeOptions.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Label("可升级项", systemImage: "arrow.up.circle")
                        .font(.subheadline.weight(.semibold))
                    ForEach(plan.upgradeOptions) { item in
                        PlanItemRow(item: item, path: $path, addToCart: addToCart)
                    }
                }
                .padding(.top, 2)
            }

            if !plan.notes.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(plan.notes.prefix(3), id: \.self) { note in
                        Label(note, systemImage: "info.circle")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(14)
        .background(Theme.Color.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.05), radius: 14, y: 6)
    }
}

private struct PlanItemRow: View {
    let item: ShoppingPlanItem
    @Binding var path: [Product]
    let addToCart: (Product, SKU?) -> Void
    private let client = APIClient()

    var body: some View {
        HStack(spacing: 10) {
            Button {
                path.append(item.product)
            } label: {
                RemoteProductImage(
                    urls: item.product.imageCandidates.compactMap { client.absoluteImageURL($0) },
                    contentMode: .fill
                ) {
                    ProgressView()
                }
                .frame(width: 58, height: 58)
                .background(Color(.tertiarySystemBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .clipped()
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(item.role)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(item.optional ? Color.secondary : Color.teal)
                    if item.optional {
                        Text("可选")
                            .font(.caption2.weight(.bold))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.secondary.opacity(0.12))
                            .clipShape(Capsule())
                    }
                }
                Text(item.product.title)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                Text(item.reason)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Spacer(minLength: 4)

            VStack(alignment: .trailing, spacing: 8) {
                Text("¥\(item.product.basePrice, specifier: "%.0f")")
                    .font(.subheadline.weight(.bold))
                    .foregroundStyle(.red)
                Button {
                    if item.product.skus.count > 1 {
                        path.append(item.product)
                    } else {
                        addToCart(item.product, item.product.skus.first)
                    }
                } label: {
                    Image(systemName: item.product.skus.count > 1 ? "slider.horizontal.3" : "cart.badge.plus")
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
            }
        }
        .padding(9)
        .background(Color.primary.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct BudgetPill: View {
    let value: Double

    var body: some View {
        Label {
            Text(value >= 0 ? "余 ¥\(value, specifier: "%.0f")" : "超 ¥\(-value, specifier: "%.0f")")
                .font(.caption.weight(.bold))
        } icon: {
            Image(systemName: value >= 0 ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(value >= 0 ? Color.green : Color.orange)
        .clipShape(Capsule())
    }
}
