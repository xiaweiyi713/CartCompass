import AVFoundation
import PhotosUI
import SafariServices
import Speech
import SwiftUI
import UIKit

struct ChatView: View {
    @Bindable var model: ChatViewModel
    @State private var path: [Product] = []
    @State private var showsCart = false
    @State private var showsProfile = false
    @State private var showsPrivacy = false
    @State private var showsModelBrain = false
    @State private var showsCamera = false
    @State private var checkoutPage: CheckoutPage?
    @State private var selectedPhoto: PhotosPickerItem?
    @State private var cameraImageData: Data?
    @State private var speechInput = SpeechInputController()
    @State private var speechOutput = SpeechOutputController()
    @State private var isListening = false
    @State private var isSpeechOutputEnabled = false
    @Environment(\.colorScheme) private var colorScheme

    private let prompts = [
        "推荐手机",
        "推荐适合油皮的防晒，200元以内，不要含酒精",
        "推荐拍照好一点的手机，4000元以内",
        "对比前两款",
        "把第一款加到购物车",
        "推荐下周三亚度假要带的东西"
    ]

    var body: some View {
        NavigationStack(path: $path) {
            VStack(spacing: 0) {
                ModeStatusBar(label: model.conversationModeLabel, isStreaming: model.isStreaming)

                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 14) {
                            ForEach(model.messages) { message in
                                MessageRow(
                                    message: message,
                                    path: $path,
                                    addToCart: { product, sku in
                                        Haptics.success()
                                        model.addToCart(product, sku: sku)
                                    },
                                    sendPrompt: { prompt in
                                        Haptics.light()
                                        model.sendQuickPrompt(prompt)
                                    }
                                )
                                    .id(message.id)
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.top, 18)
                        .padding(.bottom, 12)
                    }
                    .scrollContentBackground(.hidden)
                    .onChange(of: model.messages.count) {
                        if let id = model.messages.last?.id {
                            withAnimation(.snappy) {
                                proxy.scrollTo(id, anchor: .bottom)
                            }
                        }
                    }
                }

                QuickPromptBar(prompts: prompts) { prompt in
                    model.sendQuickPrompt(prompt)
                }

                ComposerView(
                    text: $model.inputText,
                    selectedPhoto: $selectedPhoto,
                    isStreaming: model.isStreaming,
                    isImageSearching: model.isImageSearching,
                    isListening: isListening,
                    openCamera: {
                        Haptics.light()
                        guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
                            Haptics.warning()
                            model.errorMessage = "当前设备不支持摄像头拍摄，可以改用相册上传。"
                            return
                        }
                        showsCamera = true
                    },
                    toggleSpeech: {
                        toggleSpeechInput()
                    }
                ) {
                    Haptics.light()
                    model.send()
                }
            }
            .background(AppBackdrop())
            .navigationTitle("智能导购")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    HStack(spacing: 10) {
                        Button {
                            showsProfile = true
                            model.loadProfile()
                        } label: {
                            Image(systemName: model.profile.isEmpty ? "person.crop.circle" : "person.crop.circle.badge.checkmark")
                                .font(.system(size: 21, weight: .semibold))
                        }
                        .accessibilityLabel("我的偏好")

                        Button {
                            showsModelBrain = true
                            model.loadLLMStatus()
                        } label: {
                            Image(systemName: model.llmStatus.configured ? "brain" : "brain.head.profile")
                                .font(.system(size: 20, weight: .semibold))
                        }
                        .accessibilityLabel("模型大脑")

                        Button {
                            Haptics.light()
                            isSpeechOutputEnabled.toggle()
                            if !isSpeechOutputEnabled {
                                speechOutput.stop()
                            }
                        } label: {
                            Image(systemName: isSpeechOutputEnabled ? "speaker.wave.2.fill" : "speaker.slash")
                                .font(.system(size: 20, weight: .semibold))
                        }
                        .accessibilityLabel(isSpeechOutputEnabled ? "关闭回复朗读" : "开启回复朗读")

                        Button {
                            showsPrivacy = true
                        } label: {
                            Image(systemName: "info.circle")
                                .font(.system(size: 20, weight: .semibold))
                        }
                        .accessibilityLabel("隐私与合规")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showsCart = true
                    } label: {
                        CartToolbarLabel(count: model.cart.items.reduce(0) { $0 + $1.quantity })
                    }
                    .accessibilityLabel("购物车")
                }
            }
            .sheet(isPresented: $showsCart) {
                CartView(
                    cart: model.cart,
                    isUpdating: model.isCartUpdating,
                    updateQuantity: { item, quantity in
                        model.updateCartItem(item, quantity: quantity)
                    },
                    removeItem: { item in
                        model.removeCartItem(item)
                    },
                    clearCart: {
                        model.clearCart()
                    },
                    beginSandboxCheckout: {
                        model.beginSandboxCheckout()
                    }
                )
            }
            .sheet(item: $checkoutPage) { page in
                SafariView(url: page.url)
                    .ignoresSafeArea()
            }
            .sheet(isPresented: $showsProfile) {
                ProfileView(
                    profile: model.profile,
                    isLoading: model.isProfileLoading,
                    clearProfile: {
                        model.clearProfile()
                    }
                )
            }
            .sheet(isPresented: $showsModelBrain) {
                ModelBrainView(model: model)
            }
            .sheet(isPresented: $showsPrivacy) {
                PrivacyComplianceView()
            }
            .sheet(isPresented: $showsCamera) {
                CameraCaptureView { data in
                    cameraImageData = data
                }
                .ignoresSafeArea()
            }
            .navigationDestination(for: Product.self) { product in
                ProductDetailView(product: product) { sku in
                    Haptics.success()
                    model.addToCart(product, sku: sku)
                }
            }
            .alert("请求失败", isPresented: .constant(model.errorMessage != nil)) {
                Button("知道了") {
                    Haptics.light()
                    model.errorMessage = nil
                }
            } message: {
                Text(model.errorMessage ?? "")
            }
            .onChange(of: selectedPhoto) { _, item in
                guard let item else { return }
                Task {
                    do {
                        if let data = try await item.loadTransferable(type: Data.self) {
                            model.searchByImage(data)
                        }
                    } catch {
                        await MainActor.run {
                            model.errorMessage = "读取图片失败：\(error.localizedDescription)"
                        }
                    }
                    await MainActor.run {
                        selectedPhoto = nil
                    }
                }
            }
            .onChange(of: cameraImageData) { _, data in
                guard let data else { return }
                model.searchByImage(data)
                cameraImageData = nil
            }
            .onChange(of: model.checkoutURL) { _, url in
                guard let url else { return }
                showsCart = false
                checkoutPage = CheckoutPage(url: url)
            }
            .onChange(of: model.speechOutputText) { _, text in
                guard isSpeechOutputEnabled, let text else { return }
                speechOutput.speak(text)
            }
            .onOpenURL { url in
                checkoutPage = nil
                model.handleCheckoutCallback(url)
            }
        }
    }

    private func toggleSpeechInput() {
        if isListening {
            speechInput.stop()
            isListening = false
            Haptics.light()
            return
        }
        speechInput.start(
            onTranscript: { transcript in
                model.inputText = transcript
            },
            onError: { message in
                model.errorMessage = message
                isListening = false
            },
            onFinish: {
                isListening = false
            }
        )
        isListening = true
        Haptics.light()
    }
}

private enum Haptics {
    static func light() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }

    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    static func warning() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }
}

private struct CheckoutPage: Identifiable {
    let id = UUID()
    let url: URL
}

private struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        let controller = SFSafariViewController(url: url)
        controller.preferredControlTintColor = UIColor.systemTeal
        return controller
    }

    func updateUIViewController(_ uiViewController: SFSafariViewController, context: Context) {}
}

private struct CameraCaptureView: UIViewControllerRepresentable {
    @Environment(\.dismiss) private var dismiss
    let onImageData: (Data) -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.cameraCaptureMode = .photo
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(dismiss: dismiss, onImageData: onImageData)
    }

    final class Coordinator: NSObject, UINavigationControllerDelegate, UIImagePickerControllerDelegate {
        private let dismiss: DismissAction
        private let onImageData: (Data) -> Void

        init(dismiss: DismissAction, onImageData: @escaping (Data) -> Void) {
            self.dismiss = dismiss
            self.onImageData = onImageData
        }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            defer { dismiss() }
            guard let image = info[.originalImage] as? UIImage,
                  let data = image.jpegData(compressionQuality: 0.84) else {
                return
            }
            onImageData(data)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            dismiss()
        }
    }
}

private final class SpeechInputController: NSObject {
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh_CN"))
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    func start(
        onTranscript: @escaping (String) -> Void,
        onError: @escaping (String) -> Void,
        onFinish: @escaping () -> Void
    ) {
        Task {
            let speechStatus = await requestSpeechAuthorization()
            guard speechStatus == .authorized else {
                await MainActor.run {
                    onError("语音识别权限未开启，请在系统设置中允许 ShopGuide 使用语音识别。")
                }
                return
            }
            let microphoneAllowed = await requestMicrophonePermission()
            guard microphoneAllowed else {
                await MainActor.run {
                    onError("麦克风权限未开启，请在系统设置中允许 ShopGuide 使用麦克风。")
                }
                return
            }
            do {
                try await MainActor.run {
                    try self.startRecording(onTranscript: onTranscript, onFinish: onFinish)
                }
            } catch {
                await MainActor.run {
                    onError("语音输入启动失败：\(error.localizedDescription)")
                }
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    @MainActor
    private func startRecording(onTranscript: @escaping (String) -> Void, onFinish: @escaping () -> Void) throws {
        stop()
        guard let recognizer, recognizer.isAvailable else {
            throw SpeechInputError.recognizerUnavailable
        }
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
        try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        self.request = request

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak request] buffer, _ in
            request?.append(buffer)
        }

        audioEngine.prepare()
        try audioEngine.start()

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            if let transcript = result?.bestTranscription.formattedString, !transcript.isEmpty {
                Task { @MainActor in
                    onTranscript(transcript)
                }
            }
            if error != nil || result?.isFinal == true {
                Task { @MainActor in
                    self.stop()
                    onFinish()
                }
            }
        }
    }

    private func requestSpeechAuthorization() async -> SFSpeechRecognizerAuthorizationStatus {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
    }

    private func requestMicrophonePermission() async -> Bool {
        await withCheckedContinuation { continuation in
            if #available(iOS 17.0, *) {
                AVAudioApplication.requestRecordPermission { allowed in
                    continuation.resume(returning: allowed)
                }
            } else {
                AVAudioSession.sharedInstance().requestRecordPermission { allowed in
                    continuation.resume(returning: allowed)
                }
            }
        }
    }

    private enum SpeechInputError: LocalizedError {
        case recognizerUnavailable

        var errorDescription: String? {
            "当前语音识别服务不可用，请稍后再试。"
        }
    }
}

private final class SpeechOutputController: NSObject {
    private let synthesizer = AVSpeechSynthesizer()

    func speak(_ text: String) {
        let compact = text
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !compact.isEmpty else { return }
        synthesizer.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: String(compact.prefix(220)))
        utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.92
        synthesizer.speak(utterance)
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
    }
}

private struct ModeStatusBar: View {
    let label: String
    let isStreaming: Bool

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.caption.weight(.semibold))
            Text(label)
                .font(.caption.weight(.semibold))
            if isStreaming {
                ProgressView()
                    .controlSize(.mini)
            }
            Spacer()
        }
        .foregroundStyle(.secondary)
        .padding(.horizontal, 16)
        .padding(.vertical, 7)
        .background(.ultraThinMaterial)
        .accessibilityLabel("当前模式：\(label)")
    }

    private var icon: String {
        switch label {
        case "商品知识":
            return "book.closed"
        case "天气查询":
            return "cloud.sun"
        case "旅行天气规划":
            return "cloud.sun.rain"
        case "需求澄清":
            return "questionmark.bubble"
        case "购物车操作":
            return "cart"
        case "导购推荐":
            return "sparkle.magnifyingglass"
        default:
            return "bubble.left.and.bubble.right"
        }
    }
}

private struct ModelBrainView: View {
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
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(!canSubmit || isUpdating)
        }
        .padding(.horizontal, 16)
        .padding(.top, 10)
        .padding(.bottom, 12)
        .background(.bar)
    }
}

private struct LLMModelOption: Identifiable, Hashable {
    var id: String { name }
    let name: String
    let caption: String
}

private struct LLMProviderPreset: Identifiable, Hashable {
    let id: String
    let name: String
    let subtitle: String
    let icon: String
    let gatewayProvider: String
    let baseURL: String
    let endpointNote: String
    let keyPlaceholder: String
    let models: [LLMModelOption]

    func isActive(status: LLMStatus) -> Bool {
        if gatewayProvider == "deepseek" {
            return status.configured && status.provider == "deepseek"
        }
        return status.configured && status.provider == gatewayProvider && status.baseURL == baseURL
    }

    static let all: [LLMProviderPreset] = [
        LLMProviderPreset(
            id: "deepseek",
            name: "DeepSeek",
            subtitle: "中文导购和推理能力稳定，推荐默认使用",
            icon: "sparkle.magnifyingglass",
            gatewayProvider: "deepseek",
            baseURL: "https://api.deepseek.com",
            endpointNote: "DeepSeek 官方 OpenAI-compatible Chat Completions 端点。",
            keyPlaceholder: "sk-...",
            models: [
                LLMModelOption(name: "deepseek-chat", caption: "通用导购、推荐解释、工具编排"),
                LLMModelOption(name: "deepseek-reasoner", caption: "复杂对比、订单审查、推理更强"),
                LLMModelOption(name: "deepseek-v4-flash", caption: "低延迟响应，适合演示流式对话"),
                LLMModelOption(name: "deepseek-v4-pro", caption: "更强综合能力，适合最终答辩")
            ]
        ),
        LLMProviderPreset(
            id: "openai",
            name: "OpenAI",
            subtitle: "OpenAI-compatible 接口，适合高质量自然语言回答",
            icon: "circle.hexagongrid",
            gatewayProvider: "openai_compatible",
            baseURL: "https://api.openai.com/v1",
            endpointNote: "OpenAI Chat Completions 兼容端点。",
            keyPlaceholder: "sk-...",
            models: [
                LLMModelOption(name: "gpt-4o-mini", caption: "低延迟、成本友好"),
                LLMModelOption(name: "gpt-4o", caption: "综合能力更强")
            ]
        ),
        LLMProviderPreset(
            id: "gemini",
            name: "Google Gemini",
            subtitle: "Gemini OpenAI 兼容端点，适合多模态扩展",
            icon: "diamond",
            gatewayProvider: "openai_compatible",
            baseURL: "https://generativelanguage.googleapis.com/v1beta/openai",
            endpointNote: "Google Gemini OpenAI-compatible 端点；使用 Gemini API Key。",
            keyPlaceholder: "AIza...",
            models: [
                LLMModelOption(name: "gemini-2.0-flash", caption: "低延迟，适合演示"),
                LLMModelOption(name: "gemini-1.5-pro", caption: "更强综合能力，也可填控制台最新模型名")
            ]
        ),
        LLMProviderPreset(
            id: "anthropic",
            name: "Anthropic Claude",
            subtitle: "Claude 原生 Messages API，适合复杂决策解释",
            icon: "a.square",
            gatewayProvider: "anthropic",
            baseURL: "https://api.anthropic.com/v1",
            endpointNote: "Anthropic Messages API 端点；后端会自动调用 /messages。",
            keyPlaceholder: "sk-ant-...",
            models: [
                LLMModelOption(name: "claude-3-5-sonnet-latest", caption: "推荐默认，可改成控制台最新模型名"),
                LLMModelOption(name: "claude-3-5-haiku-latest", caption: "更快更轻量")
            ]
        ),
        LLMProviderPreset(
            id: "moonshot",
            name: "Moonshot / Kimi",
            subtitle: "长上下文中文模型，适合评测和文档问答",
            icon: "moon.stars",
            gatewayProvider: "openai_compatible",
            baseURL: "https://api.moonshot.cn/v1",
            endpointNote: "Moonshot OpenAI-compatible 端点。",
            keyPlaceholder: "sk-...",
            models: [
                LLMModelOption(name: "moonshot-v1-8k", caption: "轻量快速"),
                LLMModelOption(name: "moonshot-v1-32k", caption: "更长上下文"),
                LLMModelOption(name: "moonshot-v1-128k", caption: "长文档和长对话")
            ]
        ),
        LLMProviderPreset(
            id: "qwen",
            name: "通义千问",
            subtitle: "DashScope 兼容模式，中文电商场景友好",
            icon: "cloud",
            gatewayProvider: "openai_compatible",
            baseURL: "https://dashscope.aliyuncs.com/compatible-mode/v1",
            endpointNote: "阿里云 DashScope OpenAI 兼容模式端点。",
            keyPlaceholder: "sk-...",
            models: [
                LLMModelOption(name: "qwen-turbo", caption: "低延迟"),
                LLMModelOption(name: "qwen-plus", caption: "推荐默认"),
                LLMModelOption(name: "qwen-max", caption: "更强回答质量")
            ]
        ),
        LLMProviderPreset(
            id: "zhipu",
            name: "智谱 GLM",
            subtitle: "OpenAI-compatible GLM 系列",
            icon: "brain.head.profile",
            gatewayProvider: "openai_compatible",
            baseURL: "https://open.bigmodel.cn/api/paas/v4",
            endpointNote: "智谱 BigModel OpenAI-compatible 端点。",
            keyPlaceholder: "sk-...",
            models: [
                LLMModelOption(name: "glm-4-flash", caption: "快速低成本"),
                LLMModelOption(name: "glm-4-plus", caption: "更强综合能力")
            ]
        ),
        LLMProviderPreset(
            id: "volcengine",
            name: "Volcengine Ark",
            subtitle: "火山方舟接入点，适合比赛默认云端模型",
            icon: "flame",
            gatewayProvider: "openai_compatible",
            baseURL: "https://ark.cn-beijing.volces.com/api/v3",
            endpointNote: "火山方舟 OpenAI-compatible 端点；模型名通常是控制台里的 ep- 接入点 ID。",
            keyPlaceholder: "Bearer token",
            models: [
                LLMModelOption(name: "ep-你的模型接入点", caption: "替换成方舟控制台 Endpoint ID")
            ]
        ),
        LLMProviderPreset(
            id: "openrouter",
            name: "OpenRouter",
            subtitle: "一个 Key 使用多家模型，适合 Gemini / Claude 兜底演示",
            icon: "point.3.connected.trianglepath.dotted",
            gatewayProvider: "openai_compatible",
            baseURL: "https://openrouter.ai/api/v1",
            endpointNote: "OpenRouter OpenAI-compatible 端点。",
            keyPlaceholder: "sk-or-...",
            models: [
                LLMModelOption(name: "deepseek/deepseek-chat", caption: "DeepSeek via OpenRouter"),
                LLMModelOption(name: "google/gemini-2.5-flash", caption: "Gemini via OpenRouter"),
                LLMModelOption(name: "anthropic/claude-3.5-sonnet", caption: "Claude via OpenRouter")
            ]
        ),
        LLMProviderPreset(
            id: "aihubmix",
            name: "AiHubMix",
            subtitle: "聚合模型服务，OpenAI-compatible",
            icon: "square.stack.3d.up",
            gatewayProvider: "openai_compatible",
            baseURL: "https://aihubmix.com/v1",
            endpointNote: "AiHubMix OpenAI-compatible 端点。",
            keyPlaceholder: "sk-...",
            models: [
                LLMModelOption(name: "gpt-4o-mini", caption: "快速通用"),
                LLMModelOption(name: "deepseek-chat", caption: "中文导购推荐")
            ]
        )
    ]
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
                            .foregroundStyle(.green)
                            .padding(.horizontal, 7)
                            .padding(.vertical, 2)
                            .background(Color.green.opacity(0.14), in: Capsule())
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
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 42)
                    .background(
                        LinearGradient(colors: [.teal, .blue], startPoint: .topLeading, endPoint: .bottomTrailing),
                        in: RoundedRectangle(cornerRadius: 12, style: .continuous)
                    )

                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text(preset.name)
                            .font(.headline)
                        Text(isActive ? "Active" : "Ready")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(isActive ? .green : .secondary)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background((isActive ? Color.green : Color.gray).opacity(0.14), in: Capsule())
                    }
                    Text(preset.subtitle)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: isActive ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(isActive ? .green : .secondary)
            }

            HStack(spacing: 12) {
                InfoChip(title: isActive ? (status.model ?? selectedModel) : selectedModel, icon: "cpu")
                InfoChip(title: isActive ? (status.keyHint ?? "Key 已配置") : "未配置 Key", icon: "key")
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
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
            .foregroundStyle(isSuccess ? .green : .orange)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background((isSuccess ? Color.green : Color.orange).opacity(0.12), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private struct MessageRow: View {
    let message: ChatMessage
    @Binding var path: [Product]
    let addToCart: (Product, SKU?) -> Void
    let sendPrompt: (String) -> Void

    var body: some View {
        switch message.role {
        case .user:
            HStack {
                Spacer(minLength: 48)
                Text(message.text)
                    .font(.callout)
                    .padding(.horizontal, 15)
                    .padding(.vertical, 11)
                    .background(
                        LinearGradient(
                            colors: [Color.accentColor, Color.accentColor.opacity(0.78)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .shadow(color: Color.accentColor.opacity(0.18), radius: 10, y: 4)
            }
        case .assistant:
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "sparkles")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 30, height: 30)
                    .background(
                        LinearGradient(
                            colors: [.indigo, .teal],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .clipShape(Circle())
                if message.text.isEmpty {
                    AssistantThinkingBubble()
                } else {
                    Text(message.text)
                        .font(.callout)
                        .foregroundStyle(.primary)
                        .padding(13)
                        .background(.regularMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .stroke(Color.primary.opacity(0.08), lineWidth: 0.7)
                        )
                        .transition(.opacity.combined(with: .scale(scale: 0.98, anchor: .leading)))
                }
                Spacer(minLength: 24)
            }
        case .products:
            ProductCarousel(products: message.products, path: $path, addToCart: addToCart)
        case .compare:
            if let comparison = message.comparison {
                CompareCard(comparison: comparison)
            }
        case .cart:
            if let cart = message.cart {
                CartSummaryCard(cart: cart)
            }
        case .plan:
            if let plan = message.plan {
                ShoppingPlanCard(plan: plan, path: $path, addToCart: addToCart)
            }
        case .weather:
            if let weather = message.weather {
                WeatherCard(weather: weather)
            }
        case .profile:
            if let profile = message.profile {
                ProfileSummaryCard(profile: profile)
            }
        case .fallback:
            if let fallback = message.fallback {
                FallbackCard(notice: fallback, sendPrompt: sendPrompt)
            }
        }
    }
}

private struct WeatherCard: View {
    let weather: WeatherContext

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: weatherIcon)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 30, height: 30)
                .background(Color.blue.gradient, in: Circle())

            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(weather.location.name)天气")
                            .font(.headline)
                        Text("来源：\(weather.source)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if let temp = weather.current?.temperatureC {
                        Text(String(format: "%.0f°", temp))
                            .font(.system(size: 34, weight: .bold, design: .rounded))
                    }
                }

                HStack(spacing: 10) {
                    WeatherMetric(title: "天气", value: weather.current?.condition ?? "未知")
                    if let apparent = weather.current?.apparentTemperatureC {
                        WeatherMetric(title: "体感", value: String(format: "%.0f°C", apparent))
                    }
                    if let humidity = weather.current?.humidity {
                        WeatherMetric(title: "湿度", value: String(format: "%.0f%%", humidity))
                    }
                }

                if !weather.implications.tags.isEmpty {
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 6) {
                            weatherTags
                        }
                        VStack(alignment: .leading, spacing: 6) {
                            weatherTags
                        }
                    }
                }

                if !weather.implications.shoppingNeeds.isEmpty {
                    Label("购物提醒：" + weather.implications.shoppingNeeds.prefix(4).joined(separator: "、"), systemImage: "bag")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(13)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(Color.blue.opacity(0.18), lineWidth: 1)
            )

            Spacer(minLength: 18)
        }
    }

    @ViewBuilder
    private var weatherTags: some View {
        ForEach(weather.implications.tags.prefix(4), id: \.self) { tag in
                            Text(tag)
                                .font(.caption.weight(.semibold))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 5)
                                .background(Color.blue.opacity(0.12), in: Capsule())
        }
    }

    private var weatherIcon: String {
        switch weather.current?.condition {
        case "晴":
            return "sun.max.fill"
        case "降雨", "毛毛雨":
            return "cloud.rain.fill"
        case "降雪":
            return "snowflake"
        case "雷暴":
            return "cloud.bolt.rain.fill"
        default:
            return "cloud.sun.fill"
        }
    }
}

private struct WeatherMetric: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.weight(.semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(8)
        .background(Color.primary.opacity(0.05), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct FallbackCard: View {
    let notice: FallbackNotice
    let sendPrompt: (String) -> Void

    private var tint: Color {
        switch notice.severity {
        case "error":
            return .red
        case "warning":
            return .orange
        default:
            return .teal
        }
    }

    private var icon: String {
        switch notice.code {
        case "network_failed":
            return "wifi.exclamationmark"
        case "empty_cart_checkout":
            return "cart.badge.questionmark"
        case "payment_failed", "checkout_failed":
            return "creditcard.trianglebadge.exclamationmark"
        case "image_empty", "image_failed":
            return "photo.badge.exclamationmark"
        case "model_unavailable":
            return "brain.head.profile"
        default:
            return "arrow.triangle.2.circlepath"
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 30, height: 30)
                .background(tint.gradient, in: Circle())

            VStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(notice.title)
                        .font(.subheadline.weight(.semibold))
                    Text(notice.message)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if !notice.actions.isEmpty {
                    FlowActionButtons(actions: notice.actions, tint: tint, sendPrompt: sendPrompt)
                }
            }
            .padding(13)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(tint.opacity(0.22), lineWidth: 1)
            )

            Spacer(minLength: 18)
        }
    }
}

private struct FlowActionButtons: View {
    let actions: [RecoveryAction]
    let tint: Color
    let sendPrompt: (String) -> Void

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                buttons
            }
            VStack(alignment: .leading, spacing: 8) {
                buttons
            }
        }
    }

    @ViewBuilder
    private var buttons: some View {
        ForEach(actions.prefix(3)) { action in
            Button {
                sendPrompt(action.prompt)
            } label: {
                Text(action.label)
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }
            .font(.caption.weight(.semibold))
            .buttonStyle(.plain)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(tint.opacity(0.12), in: Capsule())
            .overlay(Capsule().stroke(tint.opacity(0.25), lineWidth: 0.8))
        }
    }
}

private struct AppBackdrop: View {
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        LinearGradient(
            colors: colorScheme == .dark ? darkColors : lightColors,
            startPoint: .top,
            endPoint: .bottom
        )
        .ignoresSafeArea()
    }

    private var lightColors: [Color] {
        [
            Color(.systemBackground),
            Color(.secondarySystemBackground),
            Color(red: 0.94, green: 0.97, blue: 0.98)
        ]
    }

    private var darkColors: [Color] {
        [
            Color(red: 0.04, green: 0.055, blue: 0.065),
            Color(red: 0.075, green: 0.095, blue: 0.105),
            Color(red: 0.055, green: 0.085, blue: 0.09)
        ]
    }
}

private struct QuickPromptBar: View {
    let prompts: [String]
    let action: (String) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(prompts, id: \.self) { prompt in
                    Button(prompt) {
                        action(prompt)
                    }
                    .font(.footnote)
                    .buttonStyle(.plain)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(.thinMaterial)
                    .clipShape(Capsule())
                    .overlay(
                        Capsule()
                            .stroke(Color.primary.opacity(0.07), lineWidth: 1)
                    )
                    .controlSize(.small)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .background(.ultraThinMaterial)
    }
}

private struct ComposerView: View {
    @Binding var text: String
    @Binding var selectedPhoto: PhotosPickerItem?
    let isStreaming: Bool
    let isImageSearching: Bool
    let isListening: Bool
    let openCamera: () -> Void
    let toggleSpeech: () -> Void
    let send: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Button(action: openCamera) {
                Image(systemName: "camera")
                    .font(.system(size: 16, weight: .semibold))
                    .frame(width: 36, height: 36)
                    .background(.regularMaterial)
                    .clipShape(Circle())
            }
            .buttonStyle(.borderless)
            .disabled(isStreaming || isImageSearching)
            .accessibilityLabel("拍照找货")

            PhotosPicker(selection: $selectedPhoto, matching: .images) {
                Image(systemName: isImageSearching ? "photo.badge.clock" : "photo")
                    .font(.system(size: 16, weight: .semibold))
                    .frame(width: 36, height: 36)
                    .background(.regularMaterial)
                    .clipShape(Circle())
            }
            .buttonStyle(.borderless)
            .disabled(isStreaming || isImageSearching)
            .accessibilityLabel("上传图片")

            TextField("说出你的需求...", text: $text, axis: .vertical)
                .lineLimit(1...4)
                .textFieldStyle(.plain)
                .padding(.horizontal, 12)
                .padding(.vertical, 11)
                .background(.regularMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(Color.primary.opacity(0.06), lineWidth: 1)
                )

            Button(action: toggleSpeech) {
                Image(systemName: isListening ? "mic.circle.fill" : "mic")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(isListening ? Color.red : Color.primary)
                    .frame(width: 36, height: 36)
                    .background(.regularMaterial)
                    .clipShape(Circle())
            }
            .buttonStyle(.borderless)
            .disabled(isStreaming || isImageSearching)
            .accessibilityLabel(isListening ? "停止语音输入" : "开始语音输入")

            Button(action: send) {
                Image(systemName: isStreaming ? "hourglass" : "paperplane.fill")
                    .font(.system(size: 16, weight: .bold))
                    .frame(width: 40, height: 40)
            }
            .buttonStyle(.borderedProminent)
            .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isStreaming || isImageSearching)
            .accessibilityLabel("发送")
        }
        .padding(12)
        .background(.ultraThinMaterial)
    }
}

private struct CartToolbarLabel: View {
    let count: Int

    var body: some View {
        ZStack(alignment: .topTrailing) {
            Image(systemName: "cart")
                .font(.system(size: 21, weight: .semibold))
                .symbolRenderingMode(.hierarchical)
                .frame(width: 30, height: 30)
            if count > 0 {
                Text(count > 99 ? "99+" : "\(count)")
                    .font(.system(size: count > 9 ? 8 : 10, weight: .black))
                    .foregroundStyle(.white)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .frame(minWidth: 17, minHeight: 17)
                    .padding(.horizontal, count > 9 ? 2 : 0)
                    .background(Color(red: 0.96, green: 0.09, blue: 0.18))
                    .clipShape(Capsule())
                    .overlay(
                        Capsule()
                            .stroke(Color(.systemBackground), lineWidth: 2.2)
                    )
                    .shadow(color: .black.opacity(0.18), radius: 2, y: 1)
                    .zIndex(2)
                    .offset(x: 2, y: -2)
                    .transition(.scale.combined(with: .opacity))
                    .contentTransition(.numericText())
            }
        }
        .frame(width: 38, height: 34, alignment: .center)
        .contentShape(Rectangle())
        .animation(.snappy(duration: 0.2), value: count)
    }
}

private struct AssistantThinkingBubble: View {
    @State private var phase = false

    var body: some View {
        HStack(spacing: 7) {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .fill(Color.secondary.opacity(0.45))
                    .frame(width: 7, height: 7)
                    .scaleEffect(phase ? 1.0 : 0.58)
                    .animation(
                        .easeInOut(duration: 0.72)
                            .repeatForever()
                            .delay(Double(index) * 0.12),
                        value: phase
                    )
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 13)
        .background(.regularMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.primary.opacity(0.08), lineWidth: 0.7)
        )
        .onAppear {
            phase = true
        }
        .accessibilityLabel("正在思考")
    }
}
