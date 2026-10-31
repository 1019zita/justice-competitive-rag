import { useState } from "react";
import type { AnalysisResult } from "../../types/analysis";
import type { ProvenanceStatus } from "../../types/evidence";

type RetrievalCoverageProps = { coverage: AnalysisResult["retrievalCoverage"] };

const statusLabel: Record<ProvenanceStatus, string> = { verified: "已验证", simulated: "演示数据", unavailable: "尚未接入真实统计" };

function overallStatus(coverage: AnalysisResult["retrievalCoverage"]): ProvenanceStatus {
  const statuses = Object.values(coverage.provenance).map(field => field.status);
  if (statuses.includes("unavailable")) return "unavailable";
  if (statuses.includes("simulated")) return "simulated";
  return "verified";
}

function coverageValue<T>(value: T | undefined, status: ProvenanceStatus): T | string {
  return status === "unavailable" ? "—" : value ?? "—";
}

export function RetrievalCoverage({ coverage }: RetrievalCoverageProps) {
  const [expanded, setExpanded] = useState(false);
  const coverageStatus = overallStatus(coverage);
  return <section className="coverage-module"><button type="button" className="coverage-toggle" onClick={() => setExpanded(value => !value)} aria-expanded={expanded}><div className="module-heading"><span className="module-icon coverage-icon">◫</span><div><h3>检索覆盖</h3><p>覆盖范围和审计通过率</p></div><span className={`coverage-status-chip status-${coverageStatus}`}>{statusLabel[coverageStatus]}</span></div><span className="coverage-expand">{expanded ? "收起 ↑" : "展开详情 ↓"}</span></button><div className="coverage-stats"><div><strong>{coverageValue(coverage.candidateCount, coverage.provenance.candidateCount.status)}</strong><span>候选材料 · {statusLabel[coverage.provenance.candidateCount.status]}</span></div><div><strong>{coverageValue(coverage.authorityPassedCount, coverage.provenance.authorityPassedCount.status)}</strong><span>通过权威性核查 · {statusLabel[coverage.provenance.authorityPassedCount.status]}</span></div><div><strong>{coverageValue(coverage.applicabilityPassedCount, coverage.provenance.applicabilityPassedCount.status)}</strong><span>通过适用性核查 · {statusLabel[coverage.provenance.applicabilityPassedCount.status]}</span></div><div><strong>{coverageValue(coverage.citedCount, coverage.provenance.citedCount.status)}</strong><span>最终引用 · {statusLabel[coverage.provenance.citedCount.status]}</span></div></div>{expanded && <div className="coverage-details"><div className="coverage-detail-grid"><div><span className="detail-label">来源类型</span>{Object.entries(coverage.sourceCounts).map(([key, value]) => <div className="source-count-row" key={key}><span>{key}</span><b>{value}</b><small>{statusLabel[coverage.provenance.sourceCounts.status]}</small></div>)}</div><div><span className="detail-label">范围</span><p><b>检索时间 · {statusLabel[coverage.provenance.timeRange.status]}</b>{coverageValue(coverage.timeRange, coverage.provenance.timeRange.status)}</p><p><b>已覆盖来源 · {statusLabel[coverage.provenance.coveredSources.status]}</b>{coverage.coveredSources?.length ? coverage.coveredSources.join("、") : "—"}</p><p><b>覆盖有限 · {statusLabel[coverage.provenance.knownGaps.status]}</b>{coverage.knownGaps?.length ? coverage.knownGaps.join("、") : "—"}</p></div></div><p className="coverage-disclaimer">当前覆盖数字、时间范围和来源清单均为样板审计字段或待接入数据，不代表公开站点具有实时检索能力。</p></div>}</section>;
}
