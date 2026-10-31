import type { AnalysisResult } from "../../types/analysis";

type UnresolvedFactsProps = { items: AnalysisResult["unresolvedFacts"]; onAddFact: (fact: string) => void };

export function UnresolvedFacts({ items, onAddFact }: UnresolvedFactsProps) {
  return <section className="secondary-module unresolved-module" id="unresolved-facts"><div className="module-heading"><span className="module-icon warning-icon">!</span><div><h3>尚需核实的信息</h3><p>这些事实会直接影响当前分析的适用边界。</p></div><span className="module-count">{items.length}</span></div><div className="unresolved-list">{items.map(item => <article key={item.id}><div className={`severity-bar severity-${item.severity}`} /><div className="unresolved-copy"><strong>{item.fact}</strong><span>影响：{item.whyItMatters}</span></div><button type="button" onClick={() => onAddFact(item.fact)}>补充该事实</button></article>)}</div></section>;
}
