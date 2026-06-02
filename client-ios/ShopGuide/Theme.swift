import SwiftUI

/// User-selectable appearance, persisted via `@AppStorage` and applied with
/// `.preferredColorScheme` at the app root.
enum AppearanceMode: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: "跟随系统"
        case .light: "浅色"
        case .dark: "深色"
        }
    }

    var symbol: String {
        switch self {
        case .system: "iphone"
        case .light: "sun.max"
        case .dark: "moon.stars"
        }
    }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

/// App-wide design system: spacing, radius, color, typography, motion, and the
/// reusable "Liquid Glass" surface treatment.
///
/// Dark-mode-first: colors are tuned to glow on a deep canvas while still
/// adapting cleanly in Light mode through system materials and hierarchical
/// styles. Targeting iOS 17, the glass look is built from `ultraThinMaterial`
/// plus a highlight stroke and soft shadow (a faithful stand-in for the native
/// iOS 26 `.glassEffect()`), so it compiles and runs on the project's target.
enum Theme {
    enum Spacing {
        static let xxs: CGFloat = 4
        static let xs: CGFloat = 8
        static let sm: CGFloat = 12
        static let md: CGFloat = 16
        static let lg: CGFloat = 24
        static let xl: CGFloat = 32
    }

    enum Radius {
        static let sm: CGFloat = 14
        static let md: CGFloat = 20
        static let lg: CGFloat = 28
        static let pill: CGFloat = 999
    }

    enum Color {
        // Brand — monochrome, ChatGPT-style. `accent` adapts automatically
        // (near-black in Light, near-white in Dark). `onAccent` is the inverted
        // color placed on top of an accent-filled surface so labels stay legible
        // in both color schemes. Hierarchy comes from weight, size, and spacing
        // rather than hue.
        static let accent = SwiftUI.Color.primary
        static let accentSoft = SwiftUI.Color.primary.opacity(0.72)
        static let onAccent = SwiftUI.Color(.systemBackground)
        static let price = SwiftUI.Color.primary

        // Surfaces (names kept for backwards compatibility with existing views)
        static let cardBackground = SwiftUI.Color(.secondarySystemBackground)
        static let cardStroke = SwiftUI.Color.white.opacity(0.10)
        static let quietText = SwiftUI.Color.secondary

        // Glass detailing
        static let glassHighlight = SwiftUI.Color.white.opacity(0.18)
    }

    enum Motion {
        static let spring = Animation.spring(response: 0.42, dampingFraction: 0.82)
        static let snappy = Animation.snappy(duration: 0.28)
        static let gentle = Animation.easeInOut(duration: 0.45)
    }

    enum Gradient {
        static var brand: LinearGradient {
            LinearGradient(
                colors: [Theme.Color.accent, Theme.Color.accentSoft],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }

        /// Diagonal top-left highlight that reads as light catching a glass edge.
        static var glassStroke: LinearGradient {
            LinearGradient(
                colors: [
                    Theme.Color.glassHighlight,
                    Theme.Color.glassHighlight.opacity(0.25),
                    .clear
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        }
    }
}

// MARK: - Liquid Glass surface

/// A translucent, frosted "Liquid Glass" surface with a light-catching edge and
/// depth shadow. `elevated` controls how much the card appears to float.
struct LiquidGlass: ViewModifier {
    var radius: CGFloat = Theme.Radius.md
    var elevated: Bool = true

    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial, in: .rect(cornerRadius: radius))
            .overlay {
                RoundedRectangle(cornerRadius: radius)
                    .strokeBorder(Theme.Gradient.glassStroke, lineWidth: 1)
            }
            .shadow(color: .black.opacity(elevated ? 0.32 : 0.16),
                    radius: elevated ? 22 : 10,
                    y: elevated ? 12 : 5)
    }
}

extension View {
    /// Frosted Liquid Glass card surface.
    func liquidGlass(radius: CGFloat = Theme.Radius.md, elevated: Bool = true) -> some View {
        modifier(LiquidGlass(radius: radius, elevated: elevated))
    }

    /// Backwards-compatible alias used by existing views; now renders as glass so
    /// untouched screens inherit the new look automatically.
    func cardSurface(radius: CGFloat = Theme.Radius.lg) -> some View {
        liquidGlass(radius: radius, elevated: true)
    }
}

// MARK: - Deep canvas background

/// Dark-first ambient backdrop: a deep gradient with two soft brand-tinted
/// blobs, so glass surfaces have something rich to refract.
struct LiquidBackdrop: View {
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        ZStack {
            baseGradient
            Circle()
                .fill(Theme.Color.accent.opacity(colorScheme == .dark ? 0.22 : 0.12))
                .frame(width: 320)
                .blur(radius: 90)
                .offset(x: -120, y: -220)
            Circle()
                .fill(Theme.Color.price.opacity(colorScheme == .dark ? 0.16 : 0.08))
                .frame(width: 300)
                .blur(radius: 100)
                .offset(x: 140, y: 260)
        }
        .ignoresSafeArea()
    }

    private var baseGradient: LinearGradient {
        let dark = [
            SwiftUI.Color(red: 0.05, green: 0.06, blue: 0.08),
            SwiftUI.Color(red: 0.07, green: 0.09, blue: 0.11),
            SwiftUI.Color(red: 0.04, green: 0.06, blue: 0.07)
        ]
        let light = [
            SwiftUI.Color(.systemBackground),
            SwiftUI.Color(.secondarySystemBackground),
            SwiftUI.Color(red: 0.93, green: 0.96, blue: 0.97)
        ]
        return LinearGradient(colors: colorScheme == .dark ? dark : light,
                              startPoint: .top, endPoint: .bottom)
    }
}

// MARK: - Reusable glass tag

/// Small frosted pill used for floating labels, spec highlights, and tag clouds.
struct GlassTag: View {
    let text: String
    var systemImage: String?
    var tint: Color = Theme.Color.accent
    var prominent = false

    var body: some View {
        label
            .font(.caption.weight(.semibold))
            .foregroundStyle(prominent ? AnyShapeStyle(Theme.Color.onAccent) : AnyShapeStyle(tint))
            .padding(.horizontal, Theme.Spacing.sm)
            .padding(.vertical, Theme.Spacing.xxs + 2)
            .background {
                if prominent {
                    Capsule().fill(tint.gradient)
                } else {
                    Capsule().fill(.ultraThinMaterial)
                    Capsule().fill(tint.opacity(0.16))
                    Capsule().strokeBorder(tint.opacity(0.35), lineWidth: 0.8)
                }
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
