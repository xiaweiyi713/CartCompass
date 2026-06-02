import SwiftUI

struct CartView: View {
    let cart: CartState
    let isUpdating: Bool
    let updateQuantity: (CartItem, Int) -> Void
    let removeItem: (CartItem) -> Void
    let clearCart: () -> Void
    let beginSandboxCheckout: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var showsClearConfirmation = false
    @State private var showsCheckoutConfirmation = false

    var body: some View {
        NavigationStack {
            List {
                if cart.items.isEmpty {
                    ContentUnavailableView("购物车为空", systemImage: "cart", description: Text("在聊天里说“把第一款加到购物车”即可加入商品。"))
                } else {
                    Section("商品") {
                        ForEach(cart.items) { item in
                            CartItemRow(item: item, isUpdating: isUpdating) { quantity in
                                updateQuantity(item, quantity)
                            }
                            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                Button(role: .destructive) {
                                    removeItem(item)
                                } label: {
                                    Label("删除", systemImage: "trash")
                                }
                            }
                        }
                    }

                    Section {
                        HStack {
                            Text("合计")
                            Spacer()
                            Text("¥\(cart.totalPrice, specifier: "%.0f")")
                                .font(.title3.bold())
                                .foregroundStyle(Theme.Color.price)
                        }

                        Button {
                            showsCheckoutConfirmation = true
                        } label: {
                            Label("去沙箱结算", systemImage: "creditcard")
                                .font(.headline)
                                .foregroundStyle(Theme.Color.onAccent)
                                .frame(maxWidth: .infinity, minHeight: 44)
                                .background(Theme.Color.accent, in: .capsule)
                        }
                        .buttonStyle(.plain)
                        .disabled(isUpdating)

                        Button(role: .destructive) {
                            showsClearConfirmation = true
                        } label: {
                            Label("清空购物车", systemImage: "trash")
                                .frame(maxWidth: .infinity)
                        }
                        .disabled(isUpdating)
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(LiquidBackdrop())
            .navigationTitle("购物车")
            .toolbar {
                if !cart.items.isEmpty {
                    ToolbarItem(placement: .topBarLeading) {
                        Button("清空", role: .destructive) {
                            showsClearConfirmation = true
                        }
                        .disabled(isUpdating)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") {
                        dismiss()
                    }
                }
            }
            .confirmationDialog("清空购物车？", isPresented: $showsClearConfirmation, titleVisibility: .visible) {
                Button("清空购物车", role: .destructive) {
                    clearCart()
                }
                Button("取消", role: .cancel) {}
            }
            .confirmationDialog("创建虚拟商城结算页？", isPresented: $showsCheckoutConfirmation, titleVisibility: .visible) {
                Button("打开沙箱结算") {
                    beginSandboxCheckout()
                    dismiss()
                }
                Button("取消", role: .cancel) {}
            } message: {
                Text("合计 ¥\(cart.totalPrice, specifier: "%.0f")。支付页为演示沙箱，不会产生真实扣款。")
            }
        }
    }
}

private struct CartItemRow: View {
    let item: CartItem
    let isUpdating: Bool
    let updateQuantity: (Int) -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ProductThumbnail(product: item.product, imageURL: item.selectedSKU?.imageURL)
            VStack(alignment: .leading, spacing: 5) {
                Text(item.product.title)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(2)
                Text(item.product.brand)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let sku = item.selectedSKU {
                    Text(sku.displayText)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Text("¥\(item.unitPrice, specifier: "%.0f") x \(item.quantity)")
                    .font(.footnote)
                    .foregroundStyle(Theme.Color.price)
                HStack(spacing: 8) {
                    Button {
                        updateQuantity(item.quantity - 1)
                    } label: {
                        Image(systemName: "minus.circle")
                    }
                    .disabled(isUpdating || item.quantity <= 1)

                    Text("\(item.quantity)")
                        .font(.subheadline.monospacedDigit())
                        .frame(minWidth: 28)

                    Button {
                        updateQuantity(item.quantity + 1)
                    } label: {
                        Image(systemName: "plus.circle")
                    }
                    .disabled(isUpdating)
                }
                .buttonStyle(.borderless)
                .padding(.top, 4)
            }
        }
    }
}

struct CartSummaryCard: View {
    let cart: CartState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("购物车已更新", systemImage: "cart.fill")
                .font(.headline)
            Text("共 \(cart.items.reduce(0) { $0 + $1.quantity }) 件商品，合计 ¥\(cart.totalPrice, specifier: "%.0f")")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding(Theme.Spacing.sm)
        .liquidGlass(radius: Theme.Radius.md, elevated: false)
    }
}

private struct ProductThumbnail: View {
    let product: Product
    let imageURL: String?
    private let client = APIClient()

    init(product: Product, imageURL: String? = nil) {
        self.product = product
        self.imageURL = imageURL
    }

    var body: some View {
        RemoteProductImage(
            urls: imageCandidates.compactMap { client.absoluteImageURL($0) },
            contentMode: .fill
        ) {
            Image(systemName: "photo")
                .foregroundStyle(.secondary)
        }
        .frame(width: 64, height: 64)
        .background(Color(.tertiarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var imageCandidates: [String] {
        if let imageURL, !imageURL.isEmpty {
            return [imageURL] + product.imageCandidates.filter { $0 != imageURL }
        }
        return product.imageCandidates
    }
}
