import SwiftUI

struct PrivacyComplianceView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ComplianceRow(
                        icon: "shippingbox",
                        title: "商品数据来源",
                        text: "商品库由赛题示例数据、公开商品页面采集数据和本地清洗结果组成。详情页会显示公开来源、证据片段、评论数量和 SKU 信息。"
                    )
                    ComplianceRow(
                        icon: "photo.on.rectangle",
                        title: "图片处理",
                        text: "上传图片仅用于当前请求的图像检索。客户端不会把图片写入本地相册外的持久存储；后端按图片特征检索商品，不把上传图保存为商品素材。"
                    )
                    ComplianceRow(
                        icon: "lock.shield",
                        title: "偏好记忆",
                        text: "长期偏好只保存预算、肤质、排除品牌/成分和反馈摘要，可在“我的偏好”里查看或清除。"
                    )
                    ComplianceRow(
                        icon: "network",
                        title: "API 使用说明",
                        text: "推荐、购物车、图片检索和评测接口默认连接本机 FastAPI 服务。LLM 文案生成是可选能力；未配置 API Key 时系统使用本地确定性回复。"
                    )
                }

                Section("合规边界") {
                    Label("不模拟真实支付、物流、库存或平台售后承诺。", systemImage: "checkmark.seal")
                    Label("售后/退换货回答只基于 Demo 规则和商品来源信息。", systemImage: "doc.text.magnifyingglass")
                    Label("推荐结果会展示风险提示，避免编造未落库事实。", systemImage: "exclamationmark.shield")
                }
                .font(.footnote)
            }
            .navigationTitle("隐私与合规")
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

private struct ComplianceRow: View {
    let icon: String
    let title: String
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(.teal)
                .frame(width: 28, height: 28)
            VStack(alignment: .leading, spacing: 5) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Text(text)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }
}
