import type { AnalysisResult } from "../../types/analysis";

type OverallAssessmentProps = { assessment: AnalysisResult["overallAssessment"]; onUncertaintyClick: () => void };

const strengthLabel: Record<AnalysisResult["overallAssessment"]["strength"], string> = {
  strong: "证据支持较强",
  moderate: "中等支持",
  mixed: "证据存在明显分歧",
  insufficient: "当前证据不足",
};

export function OverallAssessment({ assessment, onUncertaintyClick }: OverallAssessmentProps) {
  return (
    <section className="assessment-card" aria-labelledby="assessment-title">
      <div className="assessment-topline"><div><span className="section-kicker">OVERALL ASSESSMENT</span><h2 id="assessment-title">综合核查</h2></div><span className={`strength-pill strength-${assessment.strength}`}><span />{strengthLabel[assessment.strength]}</span></div>
      <p className="assessment-summary">{assessment.summary}</p>
      <button type="button" className="uncertainty-callout" onClick={onUncertaintyClick}><span className="uncertainty-icon">!</span><span><strong>不确定性</strong><small>{assessment.uncertaintySummary ?? "仍有关键事实会影响结论。"}</small></span><span className="callout-arrow">↓</span></button>
    </section>
  );
}
