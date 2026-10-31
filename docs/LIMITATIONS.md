# 限制

- **受限领域 corpus**：CV-0005 覆盖有限法律领域；不是全法域法律搜索。
- **Authority / Applicability 为辅助筛查**：基于 metadata 与词汇重叠，不替代法律专业判断。
- **Dynamic Issue Spotting 尚未进行大规模 benchmark**：当前只在少量案例上验证过端到端链路。
- **Retrieval 仍使用可复现 baseline**：sparse character TF-IDF；未启用 dense / reranker。
- **部分高阶法律效力判断仍需人工确认**：包括效力状态、适用性终局判断、证据关系。
- **生成结果受 corpus coverage 约束**：未检索到的来源不会被编造；缺口会标记为 gap。
- **Follow-up 为本地 UI**：尚未实现真实追问重检索。
- **API 为最小实现**：无持久化、鉴权、队列或 streaming。
- **Provider 稳定性依赖外部服务**：LLM JSON contract 偶发失败时通过重试、compact prompt fallback 与降级状态处理。
