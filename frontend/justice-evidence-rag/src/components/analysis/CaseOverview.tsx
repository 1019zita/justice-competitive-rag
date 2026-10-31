import type { AnalysisResult } from "../../types/analysis";
import { IssueList } from "./IssueList";

type CaseOverviewProps = { result: AnalysisResult; selectedIssueId: string | null; onSelectIssue: (id: string | null) => void };

export function CaseOverview({ result, selectedIssueId, onSelectIssue }: CaseOverviewProps) {
  const coverage = result.retrievalCoverage;
  const statusLabel = "LIVE";
  const statusDetail = "实时审计";
  return <aside className="case-sidebar"><div className="sidebar-label">CASE OVERVIEW</div><section className="sidebar-section summary-section"><div className="sidebar-section-heading"><span>案件摘要</span><span className="verified-badge">✓ {result.canonicalArtifact.version} canonical</span></div><p>{result.caseSummary}</p></section><IssueList issues={result.issues} selectedIssueId={selectedIssueId} onSelect={onSelectIssue} /><section className="sidebar-section audit-status"><div className="sidebar-section-heading"><span>检索状态</span><span className="live-label"><i /> {statusLabel}</span></div><div className="audit-row"><span>权威性核查 · {statusDetail}</span><b>{coverage.authorityPassedCount} / {coverage.candidateCount}</b></div><div className="audit-row"><span>适用性核查 · {statusDetail}</span><b>{coverage.applicabilityPassedCount} / {coverage.authorityPassedCount}</b></div><div className="audit-row"><span>覆盖时间 · 实时来源元数据</span><b>{coverage.timeRange ?? "—"}</b></div></section></aside>;
}
