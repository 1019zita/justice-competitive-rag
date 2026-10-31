import type { AnalysisIssue } from "../../types/analysis";

type IssueListProps = { issues: AnalysisIssue[]; selectedIssueId: string | null; onSelect: (issueId: string | null) => void };

export function IssueList({ issues, selectedIssueId, onSelect }: IssueListProps) {
  return <section className="sidebar-section"><div className="sidebar-section-heading"><span>争点</span><small>{issues.length} 个</small></div><div className="issue-list"><button type="button" className={`issue-item ${selectedIssueId === null ? "selected" : ""}`} onClick={() => onSelect(null)}><span className="issue-number">ALL</span><span>全部争点</span>{selectedIssueId === null && <b>⌁</b>}</button>{issues.map((issue, index) => <button type="button" key={issue.id} className={`issue-item ${selectedIssueId === issue.id ? "selected" : ""}`} onClick={() => onSelect(issue.id)}><span className="issue-number">{String(index + 1).padStart(2, "0")}</span><span>{issue.title}</span>{selectedIssueId === issue.id && <b>⌁</b>}</button>)}</div></section>;
}
