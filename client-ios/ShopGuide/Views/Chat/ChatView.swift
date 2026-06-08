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
    @State private var showsSidebar = false
    @State private var showsVoiceSettings = false
    @AppStorage("shopguide.appearance") private var appearanceRaw = AppearanceMode.dark.rawValue
    @AppStorage("voice.rate.v1") private var speechRate = 0.92
    @AppStorage("voice.voiceId.v1") private var speechVoiceId = ""
    @AppStorage("voice.loop.v1") private var voiceLoopEnabled = false

    private var appearance: AppearanceMode {
        AppearanceMode(rawValue: appearanceRaw) ?? .dark
    }

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
            ZStack {
                LiquidBackdrop(forcedColorScheme: appearance.colorScheme)

                GeometryReader { proxy in
                    let windowInsets = currentWindowSafeAreaInsets
                    let safeTop = proxy.safeAreaInsets.top > 0 ? proxy.safeAreaInsets.top : windowInsets.top
                    let safeBottom = proxy.safeAreaInsets.bottom > 0 ? proxy.safeAreaInsets.bottom : windowInsets.bottom
                    let drawerWidth = min(max(proxy.size.width * 0.76, 280), 340)
                    let exposedWidth = max(proxy.size.width - drawerWidth, 0)
                    let drawerHeight = proxy.size.height + safeTop + safeBottom
                    let drawerYOffset = -safeTop

                    ZStack(alignment: .leading) {
                        chatMainLayer(topInset: safeTop, bottomInset: safeBottom)
                            .frame(width: proxy.size.width, height: proxy.size.height)
                            .offset(x: showsSidebar ? drawerWidth : 0)
                            .brightness(showsSidebar ? -0.08 : 0)
                            .scaleEffect(showsSidebar ? 0.985 : 1, anchor: .leading)
                            .overlay {
                                if showsSidebar {
                                    Rectangle()
                                        .fill(.black.opacity(0.12))
                                        .allowsHitTesting(false)
                                }
                            }
                            .allowsHitTesting(!showsSidebar)

                        ZStack(alignment: .topLeading) {
                            Rectangle()
                                .fill(.ultraThinMaterial)
                                .frame(width: drawerWidth, height: drawerHeight)
                                .offset(y: drawerYOffset)

                            SidebarView(
                                model: model,
                                isOpen: $showsSidebar,
                                topInset: safeTop,
                                openProfile: { showsSidebar = false; showsProfile = true; model.loadProfile() },
                                openModelBrain: { showsSidebar = false; showsModelBrain = true; model.loadLLMStatus() },
                                openPrivacy: { showsSidebar = false; showsPrivacy = true }
                            )
                            .frame(width: drawerWidth, height: proxy.size.height, alignment: .topLeading)
                        }
                        .frame(width: drawerWidth, height: proxy.size.height, alignment: .topLeading)
                        .overlay(alignment: .trailing) {
                            Rectangle()
                                .fill(Theme.Color.cardStroke)
                                .frame(width: 1, height: drawerHeight)
                                .offset(y: drawerYOffset)
                        }
                        .shadow(color: .black.opacity(showsSidebar ? 0.2 : 0), radius: 24, x: 8, y: 0)
                        .offset(x: showsSidebar ? 0 : -drawerWidth)

                        if showsSidebar {
                            Button(action: closeSidebar) {
                                Color.clear
                                    .frame(width: exposedWidth, height: drawerHeight)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .offset(x: drawerWidth, y: drawerYOffset)
                            .accessibilityLabel("返回聊天")
                        }
                    }
                    .frame(width: proxy.size.width, height: proxy.size.height)
                }
            }
            .ignoresSafeArea()
            .animation(.interactiveSpring(response: 0.52, dampingFraction: 0.9, blendDuration: 0.12), value: showsSidebar)
            .toolbar(.hidden, for: .navigationBar)
            .sensoryFeedback(.impact(weight: .light), trigger: model.isStreaming)
            .sensoryFeedback(.warning, trigger: model.errorMessage)
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
                    addPreference: { text in
                        model.addProfilePreference(text)
                    },
                    removePreference: { deletion in
                        model.removeProfilePreference(kind: deletion.kind, value: deletion.value, key: deletion.key)
                    },
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
            .sheet(isPresented: $showsVoiceSettings) {
                VoiceSettingsView(
                    rate: $speechRate,
                    voiceId: $speechVoiceId,
                    loopEnabled: $voiceLoopEnabled,
                    previewVoice: {
                        speechOutput.rateMultiplier = Float(speechRate)
                        speechOutput.voiceIdentifier = speechVoiceId.isEmpty ? nil : speechVoiceId
                        speechOutput.speak("你好，我是你的导购助手，这是当前的语速和音色效果。")
                    }
                )
                .presentationDetents([.medium, .large])
            }
            .sheet(isPresented: $showsCamera) {
                CameraCaptureView { data in
                    cameraImageData = data
                }
                .ignoresSafeArea()
            }
            .navigationDestination(for: Product.self) { product in
                ProductDetailView(product: product) { sku in
                    model.addToCart(product, sku: sku)
                }
            }
            .alert("请求失败", isPresented: .constant(model.errorMessage != nil)) {
                Button("知道了") {
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
                speechOutput.rateMultiplier = Float(speechRate)
                speechOutput.voiceIdentifier = speechVoiceId.isEmpty ? nil : speechVoiceId
                speechOutput.speak(text)
            }
            .onOpenURL { url in
                checkoutPage = nil
                model.handleCheckoutCallback(url)
            }
        }
    }

    private var currentWindowSafeAreaInsets: UIEdgeInsets {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
            .first { $0.isKeyWindow }?
            .safeAreaInsets ?? .zero
    }

    private func chatMainLayer(topInset: CGFloat, bottomInset: CGFloat) -> some View {
        ZStack {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        ForEach(model.messages) { message in
                            MessageRow(
                                message: message,
                                path: $path,
                                addToCart: { product, sku in
                                    model.addToCart(product, sku: sku)
                                },
                                sendPrompt: { prompt in
                                    model.sendQuickPrompt(prompt)
                                },
                                isStreaming: model.isStreaming
                                    && message.role == .assistant
                                    && message.id == model.messages.last?.id
                            )
                            .id(message.id)
                        }
                        if model.messages.count <= 1 {
                            WelcomeActionPanel(actions: welcomeActions) { prompt in
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
                .scrollIndicators(.hidden)
                .contentMargins(.top, topInset + 74, for: .scrollContent)
                .contentMargins(.bottom, bottomInset + 168, for: .scrollContent)
                .onChange(of: model.messages.count) {
                    if let id = model.messages.last?.id {
                        withAnimation(.snappy) {
                            proxy.scrollTo(id, anchor: .bottom)
                        }
                    }
                }
            }
        }
        .overlay(alignment: .top) {
            ChatTopBar(
                cartCount: model.cart.items.reduce(0) { $0 + $1.quantity },
                isSpeechOn: isSpeechOutputEnabled,
                openSidebar: { withAnimation(Theme.Motion.spring) { showsSidebar = true } },
                toggleSpeech: {
                    isSpeechOutputEnabled.toggle()
                    if !isSpeechOutputEnabled { speechOutput.stop() }
                },
                openVoiceSettings: { showsVoiceSettings = true },
                openCart: { showsCart = true }
            )
            .padding(.top, topInset)
        }
        .overlay(alignment: .bottom) {
            VStack(spacing: 8) {
                if isListening {
                    ListeningBanner(
                        partialText: model.inputText,
                        isVoiceLoop: voiceLoopEnabled,
                        stop: { toggleSpeechInput() }
                    )
                    .transition(.move(edge: .bottom).combined(with: .opacity))
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
                        guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
                            model.errorMessage = "当前设备不支持摄像头拍摄，可以改用相册上传。"
                            return
                        }
                        showsCamera = true
                    },
                    toggleSpeech: {
                        toggleSpeechInput()
                    }
                ) {
                    model.send()
                }
            }
            .padding(.horizontal, 12)
            .padding(.bottom, bottomInset + 4)
            .animation(.snappy(duration: 0.24), value: isListening)
        }
    }

    private func closeSidebar() {
        withAnimation(.interactiveSpring(response: 0.52, dampingFraction: 0.9, blendDuration: 0.12)) {
            showsSidebar = false
        }
    }

    private func toggleSpeechInput() {
        if isListening {
            speechInput.stop()
            isListening = false
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
                // Hands-free voice loop: once recognition settles, auto-send the
                // recognised text and read the reply aloud so the user can keep
                // the whole exchange voice-only.
                guard voiceLoopEnabled else { return }
                let recognised = model.inputText.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !recognised.isEmpty, !model.isStreaming else { return }
                isSpeechOutputEnabled = true
                model.send()
            }
        )
        isListening = true
    }
}


private struct ChatTopBar: View {
    let cartCount: Int
    let isSpeechOn: Bool
    let openSidebar: () -> Void
    let toggleSpeech: () -> Void
    let openVoiceSettings: () -> Void
    let openCart: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            HStack(spacing: 10) {
                Button(action: openSidebar) { topGlyph("sidebar.leading") }
                    .buttonStyle(.plain)
                    .accessibilityLabel("菜单与历史")
                Button(action: toggleSpeech) { topGlyph(isSpeechOn ? "speaker.wave.2.fill" : "speaker.slash") }
                    .buttonStyle(.plain)
                    .accessibilityLabel(isSpeechOn ? "关闭回复朗读" : "开启回复朗读")
                    .simultaneousGesture(LongPressGesture(minimumDuration: 0.4).onEnded { _ in openVoiceSettings() })
                    .contextMenu {
                        Button { openVoiceSettings() } label: {
                            Label("语音设置", systemImage: "slider.horizontal.3")
                        }
                    }
            }
            Spacer()
            Button(action: openCart) { CartToolbarLabel(count: cartCount) }
                .buttonStyle(.plain)
                .accessibilityLabel("购物车")
        }
        .padding(.horizontal, 14)
        .padding(.top, 6)
    }

    private func topGlyph(_ name: String) -> some View {
        Image(systemName: name)
            .font(.system(size: 18, weight: .semibold))
            .foregroundStyle(.primary)
            .frame(width: 44, height: 44)
            .modifier(TopCircleButtonSurface())
            .contentShape(.rect)
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
    private let audioEngine = AVAudioEngine()
    private let cloudTranscription = SpeechTranscriptionAPIService()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var audioRecorder: AVAudioRecorder?
    private var cloudRecordingURL: URL?
    private var cloudUploadTask: Task<Void, Never>?
    private var cloudAutoStopTask: Task<Void, Never>?
    private var cloudCallbacks: (
        onTranscript: (String) -> Void,
        onError: (String) -> Void,
        onFinish: () -> Void
    )?
    private var nativeTranscriptEmitted = false
    private var userStoppedNativeRecognition = false

    func start(
        onTranscript: @escaping (String) -> Void,
        onError: @escaping (String) -> Void,
        onFinish: @escaping () -> Void
    ) {
        Task {
            let speechStatus = await requestSpeechAuthorization()
            guard speechStatus == .authorized else {
                await MainActor.run {
                    onError("语音识别权限未开启，请在系统设置中允许智购罗盘使用语音识别。")
                }
                return
            }
            let microphoneAllowed = await requestMicrophonePermission()
            guard microphoneAllowed else {
                await MainActor.run {
                    onError("麦克风权限未开启，请在系统设置中允许智购罗盘使用麦克风。")
                }
                return
            }
            do {
                try await MainActor.run {
                    if let recognizer = self.preferredRecognizer() {
                        try self.startRecording(
                            recognizer: recognizer,
                            onTranscript: onTranscript,
                            onError: onError,
                            onFinish: onFinish
                        )
                    } else {
                        try self.startCloudRecording(onTranscript: onTranscript, onError: onError, onFinish: onFinish)
                    }
                }
            } catch {
                await MainActor.run {
                    onError("语音输入启动失败：\(error.localizedDescription)")
                }
            }
        }
    }

    @MainActor
    func stop() {
        if audioRecorder != nil {
            finishCloudRecording()
            return
        }
        userStoppedNativeRecognition = true
        stopNativeRecognition()
    }

    @MainActor
    private func startRecording(
        recognizer: SFSpeechRecognizer,
        onTranscript: @escaping (String) -> Void,
        onError: @escaping (String) -> Void,
        onFinish: @escaping () -> Void
    ) throws {
        stop()
        userStoppedNativeRecognition = false
        nativeTranscriptEmitted = false
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
                    self.nativeTranscriptEmitted = true
                    onTranscript(transcript)
                }
            }
            if error != nil {
                Task { @MainActor in
                    guard !self.userStoppedNativeRecognition else { return }
                    self.stopNativeRecognition()
                    if self.nativeTranscriptEmitted {
                        onFinish()
                    } else {
                        do {
                            try self.startCloudRecording(
                                onTranscript: onTranscript,
                                onError: onError,
                                onFinish: onFinish
                            )
                        } catch {
                            onError("语音输入启动失败：\(error.localizedDescription)")
                        }
                    }
                }
                return
            }
            if result?.isFinal == true {
                Task { @MainActor in
                    self.stopNativeRecognition()
                    onFinish()
                }
            }
        }
    }

    @MainActor
    private func startCloudRecording(
        onTranscript: @escaping (String) -> Void,
        onError: @escaping (String) -> Void,
        onFinish: @escaping () -> Void
    ) throws {
        stop()
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
        try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("cartcompass-speech-\(UUID().uuidString).m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]
        let recorder = try AVAudioRecorder(url: url, settings: settings)
        recorder.isMeteringEnabled = true
        recorder.prepareToRecord()
        guard recorder.record() else {
            throw SpeechInputError.cloudRecordingUnavailable
        }
        audioRecorder = recorder
        cloudRecordingURL = url
        cloudCallbacks = (onTranscript, onError, onFinish)
        cloudAutoStopTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            await MainActor.run {
                self?.finishCloudRecording()
            }
        }
    }

    @MainActor
    private func stopNativeRecognition() {
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
    private func finishCloudRecording() {
        guard let recorder = audioRecorder,
              let url = cloudRecordingURL,
              let callbacks = cloudCallbacks else {
            return
        }
        recorder.stop()
        audioRecorder = nil
        cloudRecordingURL = nil
        cloudCallbacks = nil
        cloudAutoStopTask?.cancel()
        cloudAutoStopTask = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)

        cloudUploadTask?.cancel()
        cloudUploadTask = Task { [cloudTranscription] in
            do {
                let text = try await cloudTranscription.transcribe(fileURL: url)
                try? FileManager.default.removeItem(at: url)
                await MainActor.run {
                    callbacks.onTranscript(text)
                    callbacks.onFinish()
                }
            } catch {
                try? FileManager.default.removeItem(at: url)
                await MainActor.run {
                    callbacks.onError("语音转写失败：\(error.localizedDescription)")
                }
            }
        }
    }

    private func preferredRecognizer() -> SFSpeechRecognizer? {
        let identifiers = [
            "zh-Hans-CN",
            "zh_CN",
            "zh-Hans",
            Locale.current.identifier,
            "en-US",
            "en_US"
        ]
        var seen = Set<String>()
        for identifier in identifiers where seen.insert(identifier).inserted {
            if let recognizer = SFSpeechRecognizer(locale: Locale(identifier: identifier)) {
                return recognizer
            }
        }
        return nil
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
        case cloudRecordingUnavailable

        var errorDescription: String? {
            switch self {
            case .cloudRecordingUnavailable:
                "当前设备无法启动录音。"
            }
        }
    }
}

private struct SpeechTranscriptionAPIService {
    private let client = APIClient()
    private let decoder = JSONDecoder()

    func transcribe(fileURL: URL) async throws -> String {
        var request = URLRequest(url: client.baseURL.appending(path: "/api/speech/transcribe"))
        let boundary = "Boundary-\(UUID().uuidString)"
        let audio = try Data(contentsOf: fileURL)
        request.httpMethod = "POST"
        request.timeoutInterval = 35
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = multipartBody(audio: audio, filename: fileURL.lastPathComponent, boundary: boundary)

        let (data, response) = try await URLSession.shared.data(for: request)
        try APIClient.validate(response, data: data)
        let payload = try decoder.decode(SpeechTranscriptionResponse.self, from: data)
        let text = payload.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            throw SpeechTranscriptionError.emptyResult
        }
        return text
    }

    private func multipartBody(audio: Data, filename: String, boundary: String) -> Data {
        var body = Data()
        body.append("--\(boundary)\r\n")
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n")
        body.append("Content-Type: audio/mp4\r\n\r\n")
        body.append(audio)
        body.append("\r\n--\(boundary)--\r\n")
        return body
    }
}

private struct SpeechTranscriptionResponse: Decodable {
    let text: String
}

private enum SpeechTranscriptionError: LocalizedError {
    case emptyResult

    var errorDescription: String? {
        switch self {
        case .emptyResult:
            "没有识别到语音内容。"
        }
    }
}

private extension Data {
    mutating func append(_ string: String) {
        append(Data(string.utf8))
    }
}

private final class SpeechOutputController: NSObject {
    private let synthesizer = AVSpeechSynthesizer()

    /// Playback rate as a multiplier of the system default (0.5–1.5).
    var rateMultiplier: Float = 0.92
    /// Specific voice identifier; falls back to the default zh-CN voice when nil.
    var voiceIdentifier: String?

    func speak(_ text: String) {
        let compact = text
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !compact.isEmpty else { return }
        synthesizer.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: String(compact.prefix(220)))
        if let voiceIdentifier, let voice = AVSpeechSynthesisVoice(identifier: voiceIdentifier) {
            utterance.voice = voice
        } else {
            utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
        }
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * min(max(rateMultiplier, 0.5), 1.5)
        synthesizer.speak(utterance)
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
    }

    /// Chinese voices available on the current device, for the settings picker.
    static func availableChineseVoices() -> [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix("zh") }
            .sorted { $0.name < $1.name }
    }
}

private struct ListeningBanner: View {
    let partialText: String
    let isVoiceLoop: Bool
    let stop: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "waveform")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Theme.Color.accent)
                .symbolEffect(.variableColor.iterative, options: .repeating)
            VStack(alignment: .leading, spacing: 2) {
                Text(isVoiceLoop ? "正在聆听 · 语音连续对话" : "正在聆听…")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(partialText.isEmpty ? "请开始说话，我会实时转写" : partialText)
                    .font(.callout)
                    .foregroundStyle(partialText.isEmpty ? .secondary : .primary)
                    .lineLimit(2)
                    .animation(.snappy, value: partialText)
            }
            Spacer(minLength: 8)
            Button(action: stop) {
                Image(systemName: "stop.fill")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Theme.Color.onAccent)
                    .frame(width: 34, height: 34)
                    .background(Theme.Color.accent, in: .circle)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("停止聆听")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .liquidGlass(radius: Theme.Radius.md, elevated: true)
    }
}

private struct VoiceSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @Binding var rate: Double
    @Binding var voiceId: String
    @Binding var loopEnabled: Bool
    let previewVoice: () -> Void

    private let voices = SpeechOutputController.availableChineseVoices()

    var body: some View {
        NavigationStack {
            Form {
                Section("朗读语速") {
                    Slider(value: $rate, in: 0.5...1.5, step: 0.02) {
                        Text("语速")
                    } minimumValueLabel: {
                        Image(systemName: "tortoise")
                    } maximumValueLabel: {
                        Image(systemName: "hare")
                    }
                    Text(String(format: "当前：%.2f×", rate))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section("朗读音色") {
                    Picker("音色", selection: $voiceId) {
                        Text("系统默认（中文）").tag("")
                        ForEach(voices, id: \.identifier) { voice in
                            Text(voiceLabel(voice)).tag(voice.identifier)
                        }
                    }
                    if voices.isEmpty {
                        Text("未检测到额外中文语音，可在「设置 › 辅助功能 › 朗读内容 › 声音」中下载更多音色。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Section {
                    Toggle("语音连续对话", isOn: $loopEnabled)
                    Text("开启后，说完会自动发送并朗读回复，全程免手动操作。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section {
                    Button(action: previewVoice) {
                        Label("试听当前语速与音色", systemImage: "play.circle.fill")
                    }
                }
            }
            .navigationTitle("语音设置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }

    private func voiceLabel(_ voice: AVSpeechSynthesisVoice) -> String {
        let quality: String
        switch voice.quality {
        case .premium: quality = "（高级）"
        case .enhanced: quality = "（增强）"
        default: quality = ""
        }
        return "\(voice.name)\(quality)"
    }
}

private struct MessageRow: View {
    let message: ChatMessage
    @Binding var path: [Product]
    let addToCart: (Product, SKU?) -> Void
    let sendPrompt: (String) -> Void
    var isStreaming = false

    var body: some View {
        switch message.role {
        case .user:
            HStack {
                Spacer(minLength: 48)
                Text(message.text)
                    .font(.callout)
                    .foregroundStyle(Theme.Color.onAccent)
                    .padding(.horizontal, 15)
                    .padding(.vertical, 11)
                    .background(Theme.Color.accent, in: .rect(cornerRadius: 20))
            }
        case .assistant:
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "sparkle")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Theme.Color.onAccent)
                    .frame(width: 30, height: 30)
                    .background(Theme.Color.accent, in: .circle)
                if message.text.isEmpty {
                    AssistantThinkingBubble()
                } else {
                    HStack(alignment: .bottom, spacing: 3) {
                        Text(message.text)
                            .font(.callout)
                            .foregroundStyle(.primary)
                        if isStreaming {
                            StreamingCaret()
                        }
                    }
                    .padding(13)
                    .liquidGlass(radius: Theme.Radius.md, elevated: false)
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
        case .order:
            if let order = message.order {
                OrderSummaryCard(order: order)
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
                .foregroundStyle(Theme.Color.onAccent)
                .frame(width: 30, height: 30)
                .background(Theme.Color.accent, in: .circle)

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
            .liquidGlass(radius: Theme.Radius.md, elevated: false)

            Spacer(minLength: 18)
        }
    }

    @ViewBuilder
    private var weatherTags: some View {
        ForEach(weather.implications.tags.prefix(4), id: \.self) { tag in
            GlassTag(text: tag)
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

private struct OrderSummaryCard: View {
    let order: OrderState

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Theme.Color.onAccent)
                .frame(width: 30, height: 30)
                .background(Theme.Color.accent, in: .circle)

            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("模拟订单")
                            .font(.headline)
                        Text(order.orderID)
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text("¥\(order.totalPrice, specifier: "%.0f")")
                        .font(.title3.weight(.bold))
                }

                VStack(alignment: .leading, spacing: 8) {
                    Label(order.address, systemImage: "mappin.and.ellipse")
                    Label("\(order.items.reduce(0) { $0 + $1.quantity }) 件商品 · \(order.paymentStatus)", systemImage: "shippingbox")
                }
                .font(.footnote)
                .foregroundStyle(.secondary)

                VStack(alignment: .leading, spacing: 6) {
                    ForEach(order.items.prefix(3)) { item in
                        HStack(spacing: 8) {
                            Text(item.title)
                                .lineLimit(1)
                            Spacer()
                            Text("x\(item.quantity)")
                                .foregroundStyle(.secondary)
                        }
                        .font(.caption.weight(.medium))
                    }
                    if order.items.count > 3 {
                        Text("还有 \(order.items.count - 3) 个条目")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .padding(13)
            .liquidGlass(radius: Theme.Radius.md, elevated: false)

            Spacer(minLength: 18)
        }
    }
}

private struct FallbackCard: View {
    let notice: FallbackNotice
    let sendPrompt: (String) -> Void

    // Monochrome brand: severity is conveyed by the icon glyph + copy, not hue.
    private var tint: Color { Theme.Color.accent }

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
                .foregroundStyle(Theme.Color.onAccent)
                .frame(width: 30, height: 30)
                .background(Theme.Color.accent, in: .circle)

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
            .liquidGlass(radius: Theme.Radius.md, elevated: false)

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


private struct CartToolbarLabel: View {
    let count: Int
    @Environment(\.colorScheme) private var colorScheme

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
        .frame(width: 44, height: 44, alignment: .center)
        .modifier(TopCircleButtonSurface())
        .contentShape(Rectangle())
        .animation(.snappy(duration: 0.2), value: count)
    }
}

private struct TopCircleButtonSurface: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        content
        .background(.ultraThinMaterial, in: .circle)
        .background(
            Circle()
                .fill(colorScheme == .light ? Color.white.opacity(0.93) : Color.white.opacity(0.12))
        )
        .overlay(
            Circle()
                .strokeBorder(Color.primary.opacity(colorScheme == .light ? 0.18 : 0.14), lineWidth: 1)
        )
        .shadow(color: .black.opacity(colorScheme == .light ? 0.12 : 0.24), radius: 10, y: 5)
    }
}

private struct AssistantThinkingBubble: View {
    @State private var phase = false

    var body: some View {
        Text("Thinking...")
            .font(.callout.weight(.medium))
            .foregroundStyle(.secondary)
            .opacity(phase ? 1 : 0.55)
            .animation(.easeInOut(duration: 0.85).repeatForever(autoreverses: true), value: phase)
        .padding(.horizontal, 14)
        .padding(.vertical, 13)
        .liquidGlass(radius: Theme.Radius.md, elevated: false)
        .onAppear {
            phase = true
        }
        .accessibilityLabel("Thinking")
    }
}

/// Blinking text caret shown at the tail of a streaming assistant message.
/// Falls back to a steady bar when Reduce Motion is on.
private struct StreamingCaret: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var visible = true

    var body: some View {
        RoundedRectangle(cornerRadius: 1)
            .fill(Theme.Color.accent)
            .frame(width: 2.5, height: 16)
            .opacity(visible ? 1 : 0)
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.easeInOut(duration: 0.55).repeatForever(autoreverses: true)) {
                    visible = false
                }
            }
            .accessibilityHidden(true)
    }
}
