import SwiftUI

struct ProfileView: View {
    let profile: UserProfile
    let isLoading: Bool
    let addPreference: (String) -> Void
    let removePreference: (ProfilePreferenceDeletion) -> Void
    let clearProfile: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var draftPreference = ""

    private var canAddPreference: Bool {
        !isLoading && !draftPreference.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 10) {
                        TextField("例如：酒精过敏、油皮、不要苹果", text: $draftPreference)
                            .textInputAutocapitalization(.never)
                            .submitLabel(.done)
                            .onSubmit(addDraftPreference)
                            .accessibilityLabel("长期偏好输入框")
                            .accessibilityIdentifier("profile.preference.input")

                        Button(action: addDraftPreference) {
                            Image(systemName: isLoading ? "hourglass" : "plus")
                                .font(.system(size: 15, weight: .bold))
                                .foregroundStyle(canAddPreference ? Theme.Color.onAccent : .secondary)
                                .frame(width: 44, height: 44)
                                .background {
                                    Circle()
                                        .fill(canAddPreference ? AnyShapeStyle(Theme.Color.accent) : AnyShapeStyle(.ultraThinMaterial))
                                }
                                .overlay {
                                    Circle()
                                        .strokeBorder(canAddPreference ? Theme.Color.glassHighlight : Theme.Color.cardStroke, lineWidth: 1)
                                }
                                .contentTransition(.symbolEffect(.replace))
                        }
                        .buttonStyle(.plain)
                        .disabled(!canAddPreference)
                        .accessibilityLabel("添加长期偏好")
                    }
                } header: {
                    Text("添加偏好")
                } footer: {
                    Text("Agent 会把可识别内容结构化保存；例如“酒精过敏”会变成排除成分“酒精”。")
                }

                if profile.isEmpty {
                    ContentUnavailableView("还没有长期偏好", systemImage: "person.crop.circle", description: Text("在聊天里说“记住我以后护肤品不要含酒精”即可保存。"))
                } else {
                    if let skinType = profile.skinType {
                        Section("肤质") {
                            PreferenceRow(icon: "face.smiling", title: skinType) {
                                removePreference(ProfilePreferenceDeletion(kind: "skin_type"))
                            }
                        }
                    }

                    if !profile.budgetPreferences.isEmpty {
                        Section("预算偏好") {
                            ForEach(profile.budgetPreferences.sorted(by: { $0.key < $1.key }), id: \.key) { key, value in
                                PreferenceRow(icon: "yensign.circle", title: key, value: String(format: "约 ¥%.0f", value)) {
                                    removePreference(ProfilePreferenceDeletion(kind: "budget_preferences", key: key))
                                }
                            }
                        }
                    }

                    PreferenceTagSection(title: "偏好特征", icon: "sparkles", kind: "preferred_features", values: profile.preferredFeatures, remove: removePreference)
                    PreferenceTagSection(title: "排除品牌", icon: "nosign", kind: "excluded_brands", values: profile.excludedBrands, remove: removePreference)
                    PreferenceTagSection(title: "排除成分", icon: "drop.triangle", kind: "excluded_ingredients", values: profile.excludedIngredients, remove: removePreference)
                    PreferenceTagSection(title: "常见场景", icon: "map", kind: "travel_scenario", values: profile.travelScenario, remove: removePreference)

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

    private func addDraftPreference() {
        let text = draftPreference.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isLoading else { return }
        addPreference(text)
        draftPreference = ""
    }
}

struct ProfilePreferenceDeletion {
    let kind: String
    var value: String? = nil
    var key: String? = nil
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
    var delete: (() -> Void)?

    var body: some View {
        HStack {
            Label(title, systemImage: icon)
            Spacer()
            if let value {
                Text(value)
                    .foregroundStyle(.secondary)
            }
            if let delete {
                Button(role: .destructive, action: delete) {
                    Image(systemName: "trash")
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("删除偏好 \(title)")
            }
        }
    }
}

private struct PreferenceTagSection: View {
    let title: String
    let icon: String
    let kind: String
    let values: [String]
    let remove: (ProfilePreferenceDeletion) -> Void

    var body: some View {
        if !values.isEmpty {
            Section(title) {
                ForEach(values, id: \.self) { value in
                    PreferenceRow(icon: icon, title: value) {
                        remove(ProfilePreferenceDeletion(kind: kind, value: value))
                    }
                }
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
