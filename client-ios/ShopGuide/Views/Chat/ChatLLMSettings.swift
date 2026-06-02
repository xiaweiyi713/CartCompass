import SwiftUI

struct ModelBrainView: View {
    @Bindable var model: ChatViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var searchText = ""

    private var filteredProviders: [LLMProviderPreset] {
        guard !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return LLMProviderPreset.all
        }
        return LLMProviderPreset.all.filter { preset in
            preset.name.localizedCaseInsensitiveContains(searchText)
                || preset.subtitle.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("搜索提供商...", text: $searchText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section {
                    ForEach(filteredProviders) { preset in
                        NavigationLink(value: preset) {
                            ProviderListRow(preset: preset, isActive: preset.isActive(status: model.llmStatus))
                        }
                    }
                } header: {
                    Text("提供商")
                } footer: {
                    Text("选择一个模型提供商后，下一页会自动填好 API 端点和推荐模型；你只需要输入自己的 API Key。")
                }

                Section {
                    Button(role: .destructive) {
                        model.clearLLMConfig()
                    } label: {
                        Label("恢复默认模型", systemImage: "arrow.counterclockwise")
                    }
                    .disabled(model.isLLMUpdating)

                    if let message = model.llmTestMessage {
                        ResultBanner(message: message)
                            .listRowInsets(EdgeInsets(top: 8, leading: 0, bottom: 8, trailing: 0))
                    }
                }
            }
            .navigationTitle("模型大脑")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: LLMProviderPreset.self) { preset in
                ModelProviderDetailView(model: model, preset: preset)
            }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("完成") {
                        dismiss()
                    }
                }
            }
        }
    }
}

private struct ModelProviderDetailView: View {
    @Bindable var model: ChatViewModel
    let preset: LLMProviderPreset
    @State private var showsAdvanced = false
    @State private var revealsKey = false

    var body: some View {
        Form {
            Section {
                ProviderCard(preset: preset, status: model.llmStatus, selectedModel: model.llmModel)
            }
            .listRowBackground(Color.clear)
            .listRowInsets(EdgeInsets(top: 10, leading: 16, bottom: 6, trailing: 16))

            Section {
                DisclosureGroup(isExpanded: $showsAdvanced) {
                    VStack(alignment: .leading, spacing: 8) {
                        TextField(preset.baseURL, text: $model.llmBaseURL)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                        Text(preset.endpointNote)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "server.rack")
                            .foregroundStyle(.secondary)
                        Text("API 代理端点")
                        Spacer()
                        Text("高级")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(.quaternary, in: Capsule())
                    }
                }

                VStack(alignment: .leading, spacing: 10) {
                    Label("API Key", systemImage: "key")
                        .font(.subheadline.weight(.semibold))
                    APIKeyInputBox(apiKey: $model.llmAPIKey, revealsKey: $revealsKey, placeholder: preset.keyPlaceholder)
                    Text("Key 只发送到本机后端，后端以内存态保存当前会话配置。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }

            Section {
                TextField("自定义模型名", text: $model.llmModel)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.callout.monospaced())
                ForEach(preset.models) { option in
                    Button {
                        model.llmModel = option.name
                    } label: {
                        LLMModelRow(option: option, isSelected: model.llmModel == option.name)
                    }
                    .buttonStyle(.plain)
                }
            } header: {
                Text("Models")
            } footer: {
                Text("模型名会原样传给对应服务商；如果你在控制台创建了专属接入点，也可以直接填它。")
            }

            Section {
                if model.isLLMUpdating {
                    HStack {
                        ProgressView()
                        Text("正在连接模型服务...")
                            .foregroundStyle(.secondary)
                    }
                }
                if let message = model.llmTestMessage {
                    ResultBanner(message: message)
                        .listRowInsets(EdgeInsets(top: 8, leading: 0, bottom: 8, trailing: 0))
                }
            } footer: {
                Text("模型可以替换，但商品检索、工具调用、RAG 和 Grounding Guard 始终由 ShopGuide 后端控制。")
            }
        }
        .navigationTitle(preset.name)
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom) {
            ModelBrainActionBar(
                canSubmit: model.hasLLMAPIKey,
                isUpdating: model.isLLMUpdating,
                test: { model.testLLMConnection(provider: preset.gatewayProvider, displayName: preset.name) },
                save: { model.saveLLMConfig(provider: preset.gatewayProvider, displayName: preset.name) }
            )
        }
        .onAppear {
            model.llmBaseURL = preset.baseURL
            if !preset.models.contains(where: { $0.name == model.llmModel }) {
                model.llmModel = preset.models.first?.name ?? model.llmModel
            }
        }
    }
}

private struct APIKeyInputBox: View {
    @Binding var apiKey: String
    @Binding var revealsKey: Bool
    let placeholder: String

    var body: some View {
        HStack(spacing: 10) {
            Group {
                if revealsKey {
                    TextField("在这里粘贴 API Key（\(placeholder)）", text: $apiKey)
                } else {
                    SecureField("在这里粘贴 API Key（\(placeholder)）", text: $apiKey)
                }
            }
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .font(.callout.monospaced())
            .submitLabel(.done)
            .padding(.horizontal, 12)
            .padding(.vertical, 12)
            .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(apiKey.isEmpty ? Color.primary.opacity(0.16) : Color.accentColor.opacity(0.65), lineWidth: 1)
            )

            Button {
                revealsKey.toggle()
            } label: {
                Image(systemName: revealsKey ? "eye.slash.fill" : "eye.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .frame(width: 38, height: 42)
            }
            .buttonStyle(.bordered)
            .accessibilityLabel(revealsKey ? "隐藏 API Key" : "显示 API Key")
        }
    }
}

private struct ModelBrainActionBar: View {
    let canSubmit: Bool
    let isUpdating: Bool
    let test: () -> Void
    let save: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: test) {
                Label("测试", systemImage: "bolt.circle")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(!canSubmit || isUpdating)

            Button(action: save) {
                Label("保存启用", systemImage: "checkmark.circle.fill")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Theme.Color.onAccent)
                    .frame(maxWidth: .infinity, minHeight: 36)
                    .background(Theme.Color.accent, in: .capsule)
            }
            .buttonStyle(.plain)
            .opacity(!canSubmit || isUpdating ? 0.4 : 1)
            .disabled(!canSubmit || isUpdating)
        }
        .padding(.horizontal, 16)
        .padding(.top, 10)
        .padding(.bottom, 12)
        .background(.bar)
    }
}

private struct ProviderListRow: View {
    let preset: LLMProviderPreset
    let isActive: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: preset.icon)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(isActive ? Color.accentColor : .secondary)
                .frame(width: 34, height: 34)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 10, style: .continuous))

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(preset.name)
                        .font(.subheadline.weight(.semibold))
                    if isActive {
                        Text("Active")
                            .font(.caption2.weight(.bold))
                            .foregroundStyle(Theme.Color.accent)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 2)
                            .background(Theme.Color.accent.opacity(0.14), in: .capsule)
                    }
                }
                Text(preset.subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 4)
    }
}

private struct ProviderCard: View {
    let preset: LLMProviderPreset
    let status: LLMStatus
    let selectedModel: String

    private var isActive: Bool {
        preset.isActive(status: status)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: preset.icon)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(Theme.Color.onAccent)
                    .frame(width: 42, height: 42)
                    .background(Theme.Gradient.brand, in: .rect(cornerRadius: 12))

                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text(preset.name)
                            .font(.headline)
                        Text(isActive ? "Active" : "Ready")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(isActive ? Theme.Color.accent : Color.secondary)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background((isActive ? Theme.Color.accent : Color.secondary).opacity(0.14), in: .capsule)
                    }
                    Text(preset.subtitle)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: isActive ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(isActive ? Theme.Color.accent : Color.secondary)
            }

            HStack(spacing: 12) {
                InfoChip(title: isActive ? (status.model ?? selectedModel) : selectedModel, icon: "cpu")
                InfoChip(title: isActive ? (status.keyHint ?? "Key 已配置") : "未配置 Key", icon: "key")
            }
        }
        .padding(16)
        .background(Theme.Color.cardBackground, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color.primary.opacity(0.08), lineWidth: 0.8)
        )
    }
}

private struct InfoChip: View {
    let title: String
    let icon: String

    var body: some View {
        Label(title, systemImage: icon)
            .font(.caption.weight(.semibold))
            .lineLimit(1)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.quaternary, in: Capsule())
    }
}

private struct LLMModelRow: View {
    let option: LLMModelOption
    let isSelected: Bool

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(option.name)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                Text(option.caption)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(isSelected ? Color.accentColor : Color.secondary.opacity(0.55))
        }
        .contentShape(Rectangle())
        .padding(.vertical, 4)
    }
}

private struct ResultBanner: View {
    let message: String

    private var isSuccess: Bool {
        message.contains("成功") || message.contains("启用") || message.contains("恢复")
    }

    var body: some View {
        Label(message, systemImage: isSuccess ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
            .font(.footnote.weight(.medium))
            .foregroundStyle(.primary)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.ultraThinMaterial, in: .rect(cornerRadius: 12))
    }
}
