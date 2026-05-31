import SwiftUI

enum Theme {
    enum Spacing {
        static let xxs: CGFloat = 4
        static let xs: CGFloat = 8
        static let sm: CGFloat = 12
        static let md: CGFloat = 16
        static let lg: CGFloat = 24
    }

    enum Radius {
        static let sm: CGFloat = 10
        static let md: CGFloat = 14
        static let lg: CGFloat = 18
    }

    enum Color {
        static let cardBackground = SwiftUI.Color(.secondarySystemBackground)
        static let cardStroke = SwiftUI.Color.primary.opacity(0.07)
        static let accent = SwiftUI.Color(red: 0.04, green: 0.60, blue: 0.66)
        static let price = SwiftUI.Color(red: 0.93, green: 0.19, blue: 0.22)
        static let quietText = SwiftUI.Color.secondary
    }
}

struct CardSurface: ViewModifier {
    var radius: CGFloat = Theme.Radius.lg

    func body(content: Content) -> some View {
        content
            .background(Theme.Color.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .stroke(Theme.Color.cardStroke, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.08), radius: 18, y: 8)
    }
}

extension View {
    func cardSurface(radius: CGFloat = Theme.Radius.lg) -> some View {
        modifier(CardSurface(radius: radius))
    }
}
