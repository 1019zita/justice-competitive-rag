import { useMemo, useState } from "react";
import { AlternativeExplanations } from "../components/analysis/AlternativeExplanations";
import { CaseOverview } from "../components/analysis/CaseOverview";
import { EvidenceDrawer } from "../components/analysis/EvidenceDrawer";
import { EvidenceSection } from "../components/analysis/EvidenceSection";
import { FollowUpComposer } from "../components/analysis/FollowUpComposer";
import { OverallAssessment } from "../components/analysis/OverallAssessment";
import { RetrievalCoverage } from "../components/analysis/RetrievalCoverage";
import { UnresolvedFacts } from "../components/analysis/UnresolvedFacts";
import type { AnalysisResult } from "../types/analysis";
import type { EvidenceItem } from "../types/evidence";

type AnalysisWorkspacePageProps = { result: AnalysisResult; onNewAnalysis: () => void };

export function AnalysisWorkspacePage({ result, onNewAnalysis }: AnalysisWorkspacePageProps) {
  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);
  const [drawerItem, setDrawerItem] = useState<EvidenceItem | null>(null);
  const [composerSeed, setComposerSeed] = useState("");
  const [composerKey, setComposerKey] = useState(0);
  const [followUpNotice, setFollowUpNotice] = useState("");
  const visibleSupporting = useMemo(() => selectedIssueId ? result.supportingEvidence.filter(item => item.issueIds.includes(selectedIssueId)) : result.supportingEvidence, [result.supportingEvidence, selectedIssueId]);
  const visibleWeakening = useMemo(() => selectedIssueId ? result.weakeningEvidence.filter(item => item.issueIds.includes(selectedIssueId)) : result.weakeningEvidence, [result.weakeningEvidence, selectedIssueId]);

  function scrollToUnresolved() { document.getElementById("unresolved-facts")?.scrollIntoView({ behavior: "smooth", block: "center" }); }
  function addFact(fact: string) { setComposerSeed(`补充事实：${fact}`); setComposerKey(value => value + 1); document.getElementById("follow-up-composer")?.scrollIntoView({ behavior: "smooth", block: "center" }); }
  function submitFollowUp(value: string) { setFollowUpNotice(`已记录追问：“${value}” · Phase 1 仅保留本地状态`); }

  return <div className="workspace-page"><header className="workspace-topbar"><button className="brand brand-button" type="button" onClick={onNewAnalysis} aria-label="新建分析"><span className="brand-mark">证</span><span><strong>司法证据核查助手</strong><small>司法竞争性证据工作台</small></span></button><nav className="topnav" aria-label="工作方式"><button type="button" className={result.mode === "case-analysis" ? "active" : ""} onClick={onNewAnalysis}>分析案件</button><button type="button" className={result.mode === "viewpoint-check" ? "active" : ""} onClick={onNewAnalysis}>核查观点</button></nav><div className="topbar-actions"><span className="analysis-id">{result.analysisId}</span><button className="new-analysis-button" type="button" onClick={onNewAnalysis}>＋ 新建分析</button></div></header><div className="workspace-body"><CaseOverview result={result} selectedIssueId={selectedIssueId} onSelectIssue={setSelectedIssueId} /><main className="workspace-main"><div className="workspace-main-header"><div><span className="section-kicker">ANALYSIS RESULT <span className="result-live-dot" /> LIVE</span><h1>综合核查</h1></div><div className="filter-status">{selectedIssueId ? <><span>正在查看</span><b>{result.issues.find(issue => issue.id === selectedIssueId)?.title}</b><button type="button" onClick={() => setSelectedIssueId(null)}>清除筛选 ×</button></> : <span>全部争点 · {result.supportingEvidence.length + result.weakeningEvidence.length} 条证据</span>}</div></div><OverallAssessment assessment={result.overallAssessment} onUncertaintyClick={scrollToUnresolved} /><div className="evidence-columns"><EvidenceSection title="支持当前判断的依据" subtitle="材料支持当前方向，但不等同于自动生成法律结论。" items={visibleSupporting} tone="supporting" onOpen={setDrawerItem} /><EvidenceSection title="可能削弱当前判断的依据" subtitle="主动检索可能改变当前评价的材料。" items={visibleWeakening} tone="weakening" onOpen={setDrawerItem} /></div><AlternativeExplanations items={result.alternativeExplanations} selectedIssueId={selectedIssueId} /><UnresolvedFacts items={result.unresolvedFacts} onAddFact={addFact} /><RetrievalCoverage coverage={result.retrievalCoverage} /><div id="follow-up-composer"><FollowUpComposer key={composerKey} suggestions={result.followUpSuggestions} initialValue={composerSeed} onSubmit={submitFollowUp} /></div>{followUpNotice && <div className="follow-up-notice" role="status">✓ {followUpNotice}</div>}</main></div><EvidenceDrawer item={drawerItem} onClose={() => setDrawerItem(null)} /></div>;
}
