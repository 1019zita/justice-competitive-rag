import { useEffect, useRef } from "react";
import type { EvidenceItem, ProvenanceStatus } from "../../types/evidence";

type EvidenceDrawerProps = { item: EvidenceItem | null; onClose: () => void };

const provenanceStatusLabel: Record<ProvenanceStatus, string> = { verified: "VERIFIED", simulated: "SIMULATED · 演示数据", unavailable: "当前无法自动核验" };

function displayRetrievalValue(value: string | number | undefined, status: ProvenanceStatus) {
  return status === "unavailable" ? "尚未接入真实检索轨迹" : value ?? "—";
}

function auditValue(value: string | undefined, status: ProvenanceStatus | undefined) {
  if (status === "unavailable" || !status) return "当前无法自动核验";
  return value ?? provenanceStatusLabel[status];
}

export function EvidenceDrawer({ item, onClose }: EvidenceDrawerProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!item) return;
    closeRef.current?.focus();
    function handleKeyDown(event: KeyboardEvent) { if (event.key === "Escape") onClose(); }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [item, onClose]);
  if (!item) return null;
  const retrieval = item.retrievalProvenance;
  const retrievalStatus = retrieval?.status ?? "unavailable";
  const authority = item.authorityAudit;
  const applicability = item.applicabilityAudit;
  return <div className="drawer-layer"><button className="drawer-scrim" type="button" aria-label="关闭来源详情" onClick={onClose} /><aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title"><div className="drawer-header"><div><span className="section-kicker">SOURCE DETAIL</span><h2 id="drawer-title">来源详情</h2></div><button ref={closeRef} className="drawer-close" type="button" onClick={onClose} aria-label="关闭来源详情">×</button></div><div className="drawer-body"><div className="drawer-source-head"><div className="evidence-tags"><span className="source-tag">{item.sourceType}</span><span className="authority-tag">{item.authorityLevel}</span></div><h3>{item.title}</h3><span className="drawer-origin">{item.source.origin ?? "来源信息未提供"}</span><span className="drawer-origin">doc_id: {item.source.documentId ?? "未提供"}</span></div><div className="drawer-audit-grid"><div><span>SOURCE_EVIDENCE_STATUS</span><strong>{provenanceStatusLabel[item.sourceEvidenceStatus]}</strong></div><div><span>AUTHORITY_STATUS</span><strong>{authority?.status ?? "unavailable"}</strong></div><div><span>APPLICABILITY_STATUS</span><strong>{applicability?.status ?? "unavailable"}</strong></div><div><span>RETRIEVAL_PROVENANCE_STATUS</span><strong>{provenanceStatusLabel[retrievalStatus]}</strong></div></div><section className="drawer-section"><span className="drawer-section-label">来源核查</span><p>发布主体：{authority?.publisher ?? item.source.publisher ?? "未知"}</p><p>权威层级：{authority?.authorityLevel ?? "unknown"}；效力状态：{authority?.validityStatus ?? "unknown"}</p><p>{authority?.reason ?? "当前无法自动核验"}</p></section><section className="drawer-section"><span className="drawer-section-label">适用性核查</span><p>争点相关性：{applicability?.issueRelevance ?? "unknown"}；法域匹配：{applicability?.jurisdictionFit ?? "unknown"}</p><p>时间适用性：{applicability?.temporalFit ?? "not_assessed"}；事实/法律匹配：{applicability?.factualLegalFit ?? "unknown"}</p><p>{applicability?.reason ?? "当前无法自动核验"}</p></section><p className="source-evidence-path">来源证据文件：{item.sourceEvidenceSource ?? "尚未登记来源文件"}</p><section className="drawer-section"><span className="drawer-section-label">关键依据</span><blockquote>“{item.keySentence}”</blockquote></section><section className="drawer-section"><span className="drawer-section-label">完整原文 / CV-0005 CHUNK</span><p className="source-full-text">{item.fullText ?? "当前来源未提供可展开的原文段落。"}</p></section><details className="provenance-details"><summary>为什么系统检索到这条？ <span className="provenance-summary-status">{provenanceStatusLabel[retrievalStatus]}</span></summary><div className="provenance-banner">当前为实时 CV-0005 检索轨迹；route 仅表示检索意图，不代表证据关系。Authority / Applicability Audit 是辅助筛查，不是终局法律判断。</div><dl className="provenance-list"><div><dt>query</dt><dd>{displayRetrievalValue(retrieval?.query, retrievalStatus)}</dd></div><div><dt>rank / score</dt><dd>{displayRetrievalValue(retrieval?.rank, retrievalStatus)} / {displayRetrievalValue(retrieval?.score?.toFixed(2), retrievalStatus)}</dd></div><div><dt>retrieval channel</dt><dd>{displayRetrievalValue(retrieval?.retrievalChannel, retrievalStatus)}</dd></div><div><dt>retrieval route</dt><dd>{displayRetrievalValue(retrieval?.retrievalRoute, retrievalStatus)}</dd></div><div><dt>chunk id</dt><dd>{displayRetrievalValue(retrieval?.chunkId, retrievalStatus)}</dd></div><div><dt>authority audit</dt><dd>{auditValue(retrieval?.authorityAudit, retrieval?.authorityAuditStatus)}</dd></div><div><dt>applicability audit</dt><dd>{auditValue(retrieval?.applicabilityAudit, retrieval?.applicabilityAuditStatus)}</dd></div></dl></details></div></aside></div>;
}
