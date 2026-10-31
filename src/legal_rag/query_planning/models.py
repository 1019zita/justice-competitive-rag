"""Runtime query-planning contracts for dynamic issue analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


ROUTES = ("neutral", "support", "counter")


@dataclass(frozen=True)
class PlannedQuery:
    issue_id: str
    route: str
    query: str
    rationale: str
    trigger_fact_ids: List[str] = field(default_factory=list)
    source_query_seeds: List[str] = field(default_factory=list)
    viewpoint_used: bool = False
    planner_version: str = "DYNAMIC_QUERY_PLANNER_V1"
    generation_method: str = "deterministic_issue_fact_template"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IssueQueryPlan:
    issue_id: str
    queries: List[PlannedQuery]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "queries": [query.to_dict() for query in self.queries],
        }


@dataclass(frozen=True)
class DynamicQueryPlan:
    planner_version: str
    mode: str
    viewpoint_present: bool
    issue_plans: List[IssueQueryPlan]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "planner_version": self.planner_version,
            "mode": self.mode,
            "viewpoint_present": self.viewpoint_present,
            "issue_plans": [item.to_dict() for item in self.issue_plans],
        }
