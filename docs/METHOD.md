# 方法

## 目标

在司法辅助场景中，减少单向检索带来的证据暴露不足：同时主动寻找支持与削弱当前判断的材料，并保持来源可追溯、审计可解释、失败可降级。

## 设计决策

1. **Issue 与 Query 分离**：Issue 是法律问题，query 是检索表达，二者不混同。
2. **事实结构化优先（Method B）**：先抽取带 span 的结构化事实，再识别争点，而不是端到端一次生成。
3. **竞争性检索而非单一检索**：每个 Issue 同时执行 neutral / support / counter 三路意图。
4. **Route 不是证据关系**：support / counter route 只表示检索意图，支持/削弱由 G1 内容判断决定。
5. **审计辅助而非终局判断**：Authority / Applicability Audit 只做筛查，保留 unknown / unavailable。
6. **独立 runtime prompt**：G1_RUNTIME_V1 不修改冻结实验产物。
7. **失败可降级**：事实结构化失败 → exact-span fallback；审计失败 → unavailable；G1 审计块失败 → compact prompt。

## 模块边界

- `issue_spotting`：原始文本 → 结构化事实 + 争点。
- `query_planning`：争点 → 三路检索意图 + CV-0005 稀疏检索。
- `audit`：metadata 筛查（authority / applicability）。
- `runtime_synthesis`：实时 G1 综合 + citation 校验。
- `runtime_analysis`：编排 + AnalysisResult 适配。
- `api_server`：stdlib HTTP API。
- `frontend`：React 工作台（真实 HTTP service）。
