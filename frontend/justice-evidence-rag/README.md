# 司法证据核查助手 — Phase 1 frontend

独立的正式产品前端 surface。该目录不复用 Human Gate 的 participant state machine、实验 condition、counterbalancing 或 26-event protocol。

## Run

```bash
npm install
npm run dev
npm run build
```

## Phase 1 scope

- 首页、案件输入页、分析 pipeline、分析工作台、来源详情 Drawer
- `AnalysisResult` / `EvidenceItem` contract in `src/types/`
- `AnalysisService` abstraction with deterministic `MockAnalysisService`
- CASE-01 demo chain sourced from the canonical HG2-0005 artifact paths below; UI consumes the contract rather than CASE-specific fields

## Phase 1.1 canonical artifact audit

```text
CANONICAL_ARTIFACT_VERSION = HG2-0005
```

Canonical paths:

```text
experiments/human_gate_v2/HG2-0005/EXPERIMENT_VIGNETTE_MANIFEST.json
experiments/human_gate_v2/HG2-0005/EVIDENCE_KEY_SENTENCE_AUDIT.csv
experiments/human_gate_v2/HG2-0005/CONDITION_ARTIFACTS.json
```

The CASE-01 facts displayed by the product are copied verbatim from the HG2-0005 vignette manifest. The condition artifact is stored under HG2-0005 but declares its internal `artifact_version` as HG2-0004; its SHA-256 is byte-identical to the HG2-0004 condition artifact. This is recorded in `src/mock/case01.ts` rather than silently presented as a newer content blob.

Hash audit:

| File | HG2-0005 vs HG2-0004 | HG2-0005 vs HG2-0003 |
|---|---:|---:|
| `EXPERIMENT_VIGNETTE_MANIFEST.json` | `NO` | `NO` |
| `EVIDENCE_KEY_SENTENCE_AUDIT.csv` | `YES` | `YES` |
| `CONDITION_ARTIFACTS.json` | `YES` | `NO` |

## Provenance policy

- `sourceEvidenceStatus = verified`: source title/type/origin, key sentence, and frozen source excerpt are tied to the HG2-0005 artifact paths.
- `retrievalProvenance.status = simulated`: query, rank, score, chunk id, and retrieval channel are deterministic Phase 1 mock fields. The Drawer labels them `SIMULATED · 演示数据` and states that the real retrieval trace will be generated after the formal retrieval service is connected.
- `retrievalProvenance.status = unavailable`: concrete retrieval values are hidden and replaced with `尚未接入真实检索轨迹`.
- Authority/applicability audit fields are not presented as passed when no field-level frozen audit value exists; the Drawer reports `尚未接入真实审计结果` for those unavailable fields.
- Coverage counts, time range, covered sources, and known gaps are marked field-by-field as `simulated` in `AnalysisResult.retrievalCoverage.provenance`. Coverage UI displays `演示数据` and a disclaimer.

The mock provider does not perform a network request. No new legal source or URL is invented. It can be replaced by an HTTP implementation without changing UI components.

## Curated three-case showcase

The home page exposes three static, audited sample workspaces:

- `CASE-01` 高校学籍与证书管理 — 教育行政 / 行政诉讼
- `CASE-02` 彩礼返还 — 婚姻家庭 / 民事争议
- `CASE-03` 正当防卫 — 刑事法律 / 正当防卫

Each sample is marked `审核样板 · 预置展示数据 · 非实时检索`. The independent adapter is `src/demo/demoCases.ts`; it uses only the existing HG2-0005 facts and audited key sentences. It does not alter `AnalysisResult`, `EvidenceItem`, `MockAnalysisService`, or the HTTP API contract.

## Local modes

Default local development keeps the live HTTP path:

```bash
npm run dev
```

Static demo mode:

```bash
VITE_ANALYSIS_MODE=mock VITE_DEMO_MODE=true npm run dev
```

In static mode, the input page explicitly states that submissions use the local mock provider. The public site does not request `127.0.0.1` or any external backend.

## Public showcase

- Repository: https://github.com/1019zita/justice-evidence-rag-demo
- GitHub Pages: https://1019zita.github.io/justice-evidence-rag-demo/
- Workflow: `.github/workflows/deploy-pages.yml`

The Pages build sets `VITE_ANALYSIS_MODE=mock` and `VITE_DEMO_MODE=true`. `vite.config.ts` applies the repository base path only in GitHub Actions; local development remains rooted at `/`.
