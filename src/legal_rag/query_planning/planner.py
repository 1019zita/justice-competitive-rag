"""Dynamic issue-to-query planning without frozen-case templates."""
from __future__ import annotations

from typing import Iterable, List, Mapping, Optional

from ..issue_spotting.models import CaseFactStructure, LegalIssue
from .models import DynamicQueryPlan, IssueQueryPlan, PlannedQuery, ROUTES


PLANNER_VERSION = "DYNAMIC_QUERY_PLANNER_V1"


class DynamicQueryPlanner:
    """Build route-separated retrieval intents from current issues and facts.

    The planner is deliberately deterministic in the runtime path: the current
    issue question, legal concepts, query seeds, trigger spans, and optional
    viewpoint are the only inputs.  ``planner_version`` is retained in every
    query provenance record so a later LLM planner can be compared without
    changing the retrieval contract.
    """

    def plan(
        self,
        structured_facts: CaseFactStructure,
        final_issues: Iterable[LegalIssue],
        *,
        mode: str = "case-analysis",
        viewpoint: Optional[str] = None,
    ) -> DynamicQueryPlan:
        if mode not in {"case-analysis", "viewpoint-check"}:
            raise ValueError("mode must be case-analysis or viewpoint-check")
        viewpoint_text = (viewpoint or "").strip()
        explicit = structured_facts.explicit_by_id()
        issue_plans: List[IssueQueryPlan] = []
        for issue in final_issues:
            fact_texts = [explicit[fact_id].text for fact_id in issue.trigger_fact_ids if fact_id in explicit]
            issue_plans.append(
                IssueQueryPlan(
                    issue_id=issue.issue_id,
                    queries=self._issue_queries(issue, fact_texts, mode, viewpoint_text),
                )
            )
        return DynamicQueryPlan(
            planner_version=PLANNER_VERSION,
            mode=mode,
            viewpoint_present=bool(viewpoint_text),
            issue_plans=issue_plans,
        )

    def _issue_queries(
        self,
        issue: LegalIssue,
        fact_texts: List[str],
        mode: str,
        viewpoint: str,
    ) -> List[PlannedQuery]:
        concepts = self._compact(list(issue.legal_concepts) + list(issue.inferred_legal_concepts))
        seeds = self._compact(issue.query_seeds)
        facts = self._compact(fact_texts)
        core = self._compact([issue.question, concepts, seeds, facts])
        viewpoint_used = mode == "viewpoint-check" and bool(viewpoint)
        support_tail = (
            f"当前观点：{self._compact([viewpoint])}；支持该观点所需的规则、要件与事实对应"
            if viewpoint_used
            else "支持该争点不同合理解释所需的规则、要件与事实对应"
        )
        counter_tail = (
            f"当前观点的反向解释、限制条件与不成立路径；观点：{self._compact([viewpoint])}"
            if viewpoint_used
            else "相反解释、例外、限制条件与不成立路径"
        )
        return [
            PlannedQuery(
                issue_id=issue.issue_id,
                route="neutral",
                query=self._compact([core, "法律规则 构成要件 适用条件 程序要求"]),
                rationale="围绕当前争点寻找中性规则、构成要件和程序条件；不预设结论。",
                trigger_fact_ids=list(issue.trigger_fact_ids),
                source_query_seeds=list(issue.query_seeds),
                viewpoint_used=False,
            ),
            PlannedQuery(
                issue_id=issue.issue_id,
                route="support",
                query=self._compact([core, support_tail]),
                rationale="围绕当前案件内容形成支持性检索意图；route 仅表示检索方向，不是证据关系。",
                trigger_fact_ids=list(issue.trigger_fact_ids),
                source_query_seeds=list(issue.query_seeds),
                viewpoint_used=viewpoint_used,
            ),
            PlannedQuery(
                issue_id=issue.issue_id,
                route="counter",
                query=self._compact([core, counter_tail]),
                rationale="围绕反向解释、排除条件和限制条件形成竞争性检索意图；route 不是削弱关系标签。",
                trigger_fact_ids=list(issue.trigger_fact_ids),
                source_query_seeds=list(issue.query_seeds),
                viewpoint_used=viewpoint_used,
            ),
        ]

    @staticmethod
    def _compact(values: Iterable[str]) -> str:
        seen = set()
        parts: List[str] = []
        for value in values:
            text = " ".join(str(value or "").split()).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            parts.append(text)
        return "；".join(parts)[:1200]


__all__ = ["DynamicQueryPlanner", "PLANNER_VERSION"]
