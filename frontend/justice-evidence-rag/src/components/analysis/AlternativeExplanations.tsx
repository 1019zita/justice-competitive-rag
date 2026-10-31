import type { AnalysisResult } from "../../types/analysis";

type AlternativeExplanationsProps = { items: AnalysisResult["alternativeExplanations"]; selectedIssueId: string | null };

export function AlternativeExplanations({ items, selectedIssueId }: AlternativeExplanationsProps) {
  const visible = selectedIssueId ? items.filter(item => item.issueIds?.includes(selectedIssueId)) : items;
  return <section className="secondary-module"><div className="module-heading"><span className="module-icon">≈</span><div><h3>其他合理解释</h3><p>不是附属免责声明，而是需要单独检验的替代路径。</p></div></div><div className="alternative-list">{visible.length ? visible.map((item, index) => <article key={item.id}><span>0{index + 1}</span><p>{item.text}</p></article>) : <p className="empty-module-copy">当前争点没有单独登记的替代解释，建议回到来源证据继续核对。</p>}</div></section>;
}
