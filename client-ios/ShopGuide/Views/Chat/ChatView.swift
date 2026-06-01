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

    private let welcomeActions = [
        WelcomeAction(title: "预算找货", subtitle: "手机 5000 左右", icon: "slider.horizontal.3", prompt: "推荐5000左右的手机，拍照和续航都要好一点"),
        WelcomeAction(title: "成分避雷", subtitle: "油皮防晒", icon: "checklist.checked", prompt: "推荐适合油皮的防晒，200元以内，不要含酒精"),
        WelcomeAction(title: "旅行清单", subtitle: "按天气搭配", icon: "sun.max", prompt: "推荐下周三亚度假要带的东西")
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
                            if model.messages.count <= 1 {
                                WelcomeActionPanel(actions: welcomeActions) { prompt in
                                    Haptics.light()
                                    model.sendQuickPrompt(prompt)
                                }
                                .id("welcome-actions")
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
                        .background(Theme.Color.cardBackground)
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
            .background(Theme.Color.cardBackground, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
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
            .background(Theme.Color.cardBackground, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
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
        .background(Theme.Color.cardBackground)
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
