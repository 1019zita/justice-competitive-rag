import type { EvidenceItem } from "../../types/evidence";

type EvidenceCardProps = { item: EvidenceItem; onOpen: (item: EvidenceItem) => void };

const applicabilityLabel = { high: "高度相关", medium: "中等相关", low: "相关性有限" } as const;
const authorityStatusLabel = { verified: "来源已核验", plausible: "来源可识别", unknown: "来源状态未知", unavailable: "来源核验不可用" } as const;
const auditApplicabilityLabel = {
  directly_relevant: "直接相关",
  supportive_reference: "参考性适用",
  limited: "适用性有限",
  uncertain: "适用性未知",
  not_applicable: "不直接适用",
  unavailable: "适用性核验不可用",
} as const;

export function EvidenceCard({ item, onOpen }: EvidenceCardProps) {
  const authorityStatus = item.authorityAudit?.status ?? "unavailable";
  const auditStatus = item.applicabilityAudit?.status ?? "unavailable";
  return <article className="evidence-card"><div className="evidence-tags"><span className="source-tag">{item.sourceType}</span><span className="authority-tag">{item.authorityLevel}</span><span className="applicability-tag applicability-{item.applicability.level}">{applicabilityLabel[item.applicability.level]}</span><span className="source-tag">{authorityStatusLabel[authorityStatus]}</span><span className="source-tag">{auditApplicabilityLabel[auditStatus]}</span></div><h4>{item.title}</h4><p className="evidence-key-sentence">“{item.keySentence}”</p><div className="evidence-meta"><span><b>为什么重要</b>{item.relevanceReason}</span><span className="applicability-line"><i className={`level-dot level-${item.applicability.level}`} />{item.applicability.reason}</span></div><button type="button" className="source-link" onClick={() => onOpen(item)}>查看来源原文 <span>↗</span></button></article>;
}
