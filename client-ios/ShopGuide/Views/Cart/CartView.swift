import SwiftUI

struct CartView: View {
    let cart: CartState
    let isUpdating: Bool
    let updateQuantity: (CartItem, Int) -> Void
    let removeItem: (CartItem) -> Void
    let clearCart: () -> Void
    let beginSandboxCheckout: () -> Void
    @Environment(\.dismiss) private var dismiss
    @AppStorage("shopguide.appearance") private var appearanceRaw = AppearanceMode.dark.rawValue
    @State private var showsClearConfirmation = false
    @State private var showsCheckoutConfirmation = false

    private var appearance: AppearanceMode {
        AppearanceMode(rawValue: appearanceRaw) ?? .dark
    }

    var body: some View {
        ZStack {
            LiquidBackdrop(forcedColorScheme: appearance.colorScheme)

            GeometryReader { proxy in
                VStack(alignment: .leading, spacing: 0) {
                    header
                        .padding(.horizontal, Theme.Spacing.lg)
                        .padding(.top, proxy.safeAreaInsets.top + Theme.Spacing.md)
                        .padding(.bottom, Theme.Spacing.md)

                    ScrollView {
                        if cart.items.isEmpty {
                            emptyState
                                .frame(maxWidth: .infinity)
                                .padding(.top, 96)
                        } else {
                            VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
                                Text("商品")
                                    .font(.headline)
                                    .foregroundStyle(.secondary)
                                    .padding(.horizontal, Theme.Spacing.lg)

                                VStack(spacing: Theme.Spacing.sm) {
                                    ForEach(cart.items) { item in
                                        CartItemRow(item: item, isUpdating: isUpdating) { quantity in
                                            updateQuantity(item, quantity)
                                        } remove: {
                                            removeItem(item)
                                        }
                                    }
                                }
                                .padding(.horizontal, Theme.Spacing.lg)

                                checkoutSummary
                                    .padding(.horizontal, Theme.Spacing.lg)
                            }
                            .padding(.bottom, proxy.safeAreaInsets.bottom + Theme.Spacing.xl)
                        }
                    }
                    .scrollIndicators(.hidden)
                }
            }
        }
        .ignoresSafeArea()
        .preferredColorScheme(appearance.colorScheme)
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

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.lg) {
            HStack {
                if !cart.items.isEmpty {
                    Button("清空", role: .destructive) {
                        showsClearConfirmation = true
                    }
                    .buttonStyle(CartHeaderButtonStyle())
                    .disabled(isUpdating)
                } else {
                    Color.clear.frame(width: 72, height: 44)
                }

                Spacer()

                Button("完成") {
                    dismiss()
                }
                .buttonStyle(CartHeaderButtonStyle())
            }

            Text("购物车")
                .font(.largeTitle.bold())
        }
    }

    private var emptyState: some View {
        VStack(spacing: Theme.Spacing.md) {
            Image(systemName: "cart")
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(.secondary)
                .frame(width: 72, height: 72)
                .liquidGlass(radius: Theme.Radius.lg, elevated: false)
            Text("购物车为空")
                .font(.title3.bold())
            Text("在聊天里说“把第一款加到购物车”即可加入商品。")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, Theme.Spacing.xl)
        }
    }

    private var checkoutSummary: some View {
        VStack(spacing: Theme.Spacing.md) {
            HStack {
                Text("合计")
                    .font(.title3.weight(.medium))
                Spacer()
                Text("¥\(cart.totalPrice, specifier: "%.0f")")
                    .font(.title2.bold())
                    .foregroundStyle(Theme.Color.price)
            }

            Divider().overlay(Theme.Color.cardStroke)

            Button {
                showsCheckoutConfirmation = true
            } label: {
                Label("去沙箱结算", systemImage: "creditcard")
                    .font(.headline)
                    .foregroundStyle(Theme.Color.onAccent)
                    .frame(maxWidth: .infinity, minHeight: 48)
                    .background(Theme.Color.accent, in: .capsule)
            }
            .buttonStyle(.plain)
            .disabled(isUpdating)

            Divider().overlay(Theme.Color.cardStroke)

            Button(role: .destructive) {
                showsClearConfirmation = true
            } label: {
                Label("清空购物车", systemImage: "trash")
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .disabled(isUpdating)
        }
        .padding(Theme.Spacing.md)
        .liquidGlass(radius: Theme.Radius.lg, elevated: false)
    }
}

private struct CartItemRow: View {
    let item: CartItem
    let isUpdating: Bool
    let updateQuantity: (Int) -> Void
    let remove: () -> Void

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
            Spacer(minLength: Theme.Spacing.xs)
            Button(role: .destructive, action: remove) {
                Image(systemName: "trash")
                    .font(.system(size: 15, weight: .semibold))
                    .frame(width: 34, height: 34)
            }
            .buttonStyle(.borderless)
            .disabled(isUpdating)
        }
        .padding(Theme.Spacing.sm)
        .liquidGlass(radius: Theme.Radius.lg, elevated: false)
    }
}

private struct CartHeaderButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(.primary)
            .padding(.horizontal, Theme.Spacing.md)
            .frame(minWidth: 72, minHeight: 44)
            .background(.ultraThinMaterial, in: .capsule)
            .overlay(Capsule().strokeBorder(Theme.Color.cardStroke, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.72 : 1)
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
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var imageCandidates: [String] {
        if let imageURL, !imageURL.isEmpty {
            return [imageURL] + product.imageCandidates.filter { $0 != imageURL }
        }
        return product.imageCandidates
    }
}
