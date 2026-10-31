# 架构

## 运行时主链

```
raw case facts
→ Issue Spotting B（结构化事实 → 争点识别）
→ Dynamic Query Planner V1
→ Shared-corpus Sparse TF-IDF 检索（neutral / support / counter）
→ Runtime Authority Audit + Applicability Audit
→ G1_RUNTIME_V1 grounded synthesis
→ AnalysisResult adapter
→ POST /api/analysis
→ HttpAnalysisService
→ React Evidence Workspace
```

## Bounded Corpus

- 生产使用本地 CV-0005（通过 `LEGAL_RAG_CORPUS_PATH` 指定）。
- 仓库内置 `data/sample_corpus` 作为开箱即测的示例语料。
- `shared_runtime` scope 在检索索引建立前排除指定 `exclude_doc_ids`，不依赖 CASE-specific scope。
- 不重建向量库，不重新生成 embedding。

## Dynamic Issue Spotting

- 输入仅为原始案件文本；不依赖 `case_id`、frozen issue、frozen hypothesis、H1-H6。
- Fact Structurer 抽取 parties/actors/events/timeline/disputed actions/missing facts，并记录 Unicode span。
- 事实结构化失败时使用 deterministic exact-span fallback，并标记降级。

## Dynamic Query Planning

- 每个 Issue 独立生成 neutral / support / counter 三路 query。
- Query 由当前 issue 问题、法律概念、query seeds、trigger fact spans、可选 viewpoint 组成。
- Mode A（案件分析）不预设观点；Mode B（观点核查）围绕用户 viewpoint 生成支持/反向检索意图。
- 每条 query 保留 `issue_id`、`route`、`rationale`、`planner_version`、`trigger_fact_ids`。

## Competitive Retrieval

- 复用 CV-0005 / `SparseTfidfIndex`，三路独立检索，独立打分，独立 trace。
- `route` 是检索意图，不是返回文档的法律关系。支持/削弱归类来自 G1 的内容判断与 citation。

## Runtime Audit

- **Authority Audit**：基于 metadata 的来源身份/权威层级筛查。数据库宿主 ≠ 权威发布机构。字段不足 → `unknown` / `unavailable`。
- **Applicability Audit**：基于 metadata + 词汇重叠的争点相关性/法域/时间/事实匹配筛查。不输出终局法律结论。
- 任一审计失败 → `status = unavailable`，**不阻塞** RAG 主链。

## Synthesis

- 独立 prompt `G1_RUNTIME_V1`（不复用冻结实验 prompt）。
- 每个 claim 必须引用当前 `evidence_id`；validator 拒绝未知 ID。
- Authority / Applicability Audit 作为辅助信号传入 G1 prompt，并明确标注为“筛查信号，非终局判断”。

## Frontend

- 正式默认 `HttpAnalysisService`，不静默回退到 mock。
- Evidence Card / Drawer 展示来源核查、适用性核查、检索轨迹。
- Follow-up 保留本地 UI，不假装执行新的 retrieval。

## Human Gate 独立实验系统

Human Gate 是研究评价模块，**不是**正式产品 runtime 的必经步骤。本仓库不包含 participant-level 原始记录或冻结实验 artifacts。
