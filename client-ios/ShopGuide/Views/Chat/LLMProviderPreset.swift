import Foundation

struct LLMModelOption: Identifiable, Hashable {
    var id: String { name }
    let name: String
    let caption: String
}

struct LLMProviderPreset: Identifiable, Hashable {
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
