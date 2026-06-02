import SwiftUI

struct ProfileView: View {
    let profile: UserProfile
    let isLoading: Bool
    let clearProfile: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if profile.isEmpty {
                    ContentUnavailableView("还没有长期偏好", systemImage: "person.crop.circle", description: Text("在聊天里说“记住我以后护肤品不要含酒精”即可保存。"))
                } else {
                    if let skinType = profile.skinType {
                        Section("肤质") {
                            PreferenceRow(icon: "face.smiling", title: skinType)
                        }
                    }

                    if !profile.budgetPreferences.isEmpty {
                        Section("预算偏好") {
                            ForEach(profile.budgetPreferences.sorted(by: { $0.key < $1.key }), id: \.key) { key, value in
                                PreferenceRow(icon: "yensign.circle", title: key, value: String(format: "约 ¥%.0f", value))
                            }
                        }
                    }

                    PreferenceTagSection(title: "偏好特征", icon: "sparkles", values: profile.preferredFeatures)
                    PreferenceTagSection(title: "排除品牌", icon: "nosign", values: profile.excludedBrands)
                    PreferenceTagSection(title: "排除成分", icon: "drop.triangle", values: profile.excludedIngredients)
                    PreferenceTagSection(title: "常见场景", icon: "map", values: profile.travelScenario)

                    Section {
                        Button(role: .destructive) {
                            clearProfile()
                        } label: {
                            Label(isLoading ? "正在清除..." : "清除我的偏好", systemImage: "trash")
                        }
                        .disabled(isLoading)
                    }
                }
            }
            .navigationTitle("我的偏好")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") {
                        dismiss()
                    }
                }
            }
        }
    }
}

struct ProfileSummaryCard: View {
    let profile: UserProfile

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(profile.isEmpty ? "暂无长期偏好" : "已更新我的偏好", systemImage: "person.crop.circle.badge.checkmark")
                .font(.headline)

            if profile.isEmpty {
                Text("你可以让我记住预算、肤质、排除品牌或成分。")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else {
                FlowTags(values: summaryTags)
            }
        }
        .padding(Theme.Spacing.md)
        .liquidGlass(radius: Theme.Radius.md, elevated: false)
    }

    private var summaryTags: [String] {
        var tags: [String] = []
        if let skinType = profile.skinType {
            tags.append(skinType)
        }
        tags += profile.budgetPreferences.map { "\($0.key) ¥\(Int($0.value))" }
        tags += profile.preferredFeatures
        tags += profile.excludedBrands.map { "不买\($0)" }
        tags += profile.excludedIngredients.map { "避开\($0)" }
        tags += profile.travelScenario
        return tags
    }
}

private struct PreferenceRow: View {
    let icon: String
    let title: String
    var value: String?

    var body: some View {
        HStack {
            Label(title, systemImage: icon)
            Spacer()
            if let value {
                Text(value)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct PreferenceTagSection: View {
    let title: String
    let icon: String
    let values: [String]

    var body: some View {
        if !values.isEmpty {
            Section(title) {
                FlowTags(values: values, icon: icon)
                    .padding(.vertical, 2)
            }
        }
    }
}

private struct FlowTags: View {
    let values: [String]
    var icon: String?

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 86), spacing: 8)], alignment: .leading, spacing: 8) {
            ForEach(values, id: \.self) { value in
                HStack(spacing: 5) {
                    if let icon {
                        Image(systemName: icon)
                            .font(.caption2)
                    }
                    Text(value)
                        .font(.caption.weight(.semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.75)
                }
                .padding(.horizontal, 9)
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.accentColor.opacity(0.11))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
        }
    }
}
