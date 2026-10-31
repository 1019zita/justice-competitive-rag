import type { EvidenceItem } from "../../types/evidence";
import { EvidenceCard } from "./EvidenceCard";

type EvidenceSectionProps = { title: string; subtitle: string; items: EvidenceItem[]; tone: "supporting" | "weakening"; onOpen: (item: EvidenceItem) => void };

export function EvidenceSection({ title, subtitle, items, tone, onOpen }: EvidenceSectionProps) {
  return <section className={`evidence-section evidence-section-${tone}`}><div className="section-title-row"><div><div className="section-title-with-marker"><span className="direction-marker" /> <h3>{title}</h3></div><p>{subtitle}</p></div><span className="evidence-count">{items.length.toString().padStart(2, "0")} 条</span></div><div className="evidence-list">{items.length ? items.map(item => <EvidenceCard item={item} onOpen={onOpen} key={item.id} />) : <div className="empty-evidence">当前争点没有可展示材料。</div>}</div></section>;
}
