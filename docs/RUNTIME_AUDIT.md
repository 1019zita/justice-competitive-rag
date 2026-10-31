# Runtime Authority & Applicability Audit

版本：`RUNTIME_AUDIT_MVP_V1`

## Authority Audit

输入：retrieved evidence 的 metadata（`doc_id`、`title`、`source_origin`、`publisher`、`document_type`、`validity_status`、`jurisdiction`、`publication_date`）。

输出：

| 字段 | 取值 |
|---|---|
| `status` | `verified` / `plausible` / `unknown` / `unavailable` |
| `source_identity_status` | `verified` / `unknown` / `unavailable` |
| `authority_level` | `statute` / `judicial_interpretation` / `guiding_case` / `court_judgment` / `policy_document` / `other` / `unknown` |
| `validity_status` | `in_force` / `amended` / `repealed` / `superseded` / `historical` / `unknown` / `not_assessed` |
| `publisher` | 明确发布主体，缺失则为 `null` |
| `provenance_fields` | 实际参与判断的字段清单 |

规则：

- `verified`：document identity 完整 + publisher 明确 + document type 明确。
- `plausible`：document identity 与 type 可识别，但 publisher 缺失。
- `unknown`：字段不足以确认权威层级。
- `unavailable`：审计失败。**不阻塞** RAG。

**宿主 ≠ 权威**：商业数据库、裁判文书网等 discovery/host source 不会被提升为发布机关。

## Applicability Audit

输入：案件事实 + 当前 issue + retrieved evidence + authority audit。

输出：

| 字段 | 取值 |
|---|---|
| `status` | `directly_relevant` / `supportive_reference` / `limited` / `uncertain` / `not_applicable` / `unavailable` |
| `issue_relevance` | `fit` / `mismatch` / `unknown` |
| `jurisdiction_fit` | `fit` / `mismatch` / `unknown` |
| `temporal_fit` | `fit` / `not_assessed` |
| `factual_legal_fit` | `fit` / `unknown` |
| `reason` | 一句简短解释 |

规则（MVP，metadata + 词汇重叠）：

- 争点术语与证据内容重叠 ≥ 3 → issue relevance = fit。
- jurisdiction 匹配中国大陆法域 → fit；缺失 → unknown。
- 有 publication_date → temporal_fit = fit，否则 not_assessed。
- 直接相关 = issue fit + authority verified + jurisdiction fit + temporal fit。
- 参考性 = issue/fact fit 但至少一个维度未确认。
- 不确定 = 只有部分线索。

这不是终局法律判断。`limited` 证据不会被写成“直接适用”；`historical` / `repealed` 不会被当作当前有效规则。

## Fail-safe

- 任一审计 helper 失败 → 该 evidence 对应状态 `unavailable`。
- G1 带审计 prompt 失败 → 自动回退到 compact prompt（无审计块），并在 `runtimeWarnings` 中记录 `audit_prompt_fallback`。
- **审计失败不会阻塞整体 RAG。**

## 与 G1 的关系

审计结果作为辅助信号传入 G1 prompt，明确声明：

> Audit metadata provides screening signals, not final legal truth.

`unknown` 不解释为 verified；`unavailable` 不解释为 failed。

## 与前端的关系

- Evidence Card：`来源已核验 / 来源可识别 / 来源状态未知`、`直接相关 / 参考性适用 / 适用性有限 / 适用性未知`。
- Evidence Drawer：来源核查（发布主体 / 权威层级 / 效力状态）+ 适用性核查（争点相关性 / 法域 / 时间 / 事实匹配）。
- 不生成综合可信度分；各审计维度独立呈现。
