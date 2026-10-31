"""Reusable data models for Dynamic Legal Issue Spotting.

This module is intentionally independent from the frozen-case L2 models.  It has
no case_id, issue registry, hypothesis registry, or frozen-workbook dependency.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ISSUE_TYPES = (
    "substantive",
    "procedural",
    "jurisdictional",
    "evidentiary",
    "remedy",
    "mixed",
    "unknown",
)
IMPORTANCE_LEVELS = ("high", "medium", "low")
CONFIDENCE_LEVELS = ("high", "medium", "low")
PROVENANCE_STAGES = ("initial", "retrieval_refined")
REFINEMENT_ACTIONS = (
    "KEEP",
    "MERGE",
    "SPLIT",
    "ADD",
    "DROP",
    "REFORMULATE",
)


@dataclass(frozen=True)
class DynamicCaseInput:
    """Raw user-provided case facts; no configured case identity is required."""

    facts_text: str
    source_label: str = "user_input"

    def __post_init__(self) -> None:
        if not isinstance(self.facts_text, str) or not self.facts_text.strip():
            raise ValueError("facts_text must be a non-empty string")
        if not isinstance(self.source_label, str) or not self.source_label.strip():
            raise ValueError("source_label must be a non-empty string")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts_text": self.facts_text,
            "source_label": self.source_label,
        }


@dataclass
class FactSpan:
    """One fact-like item with a Unicode code-point span into raw case facts."""

    fact_id: str
    text: str
    source_span: Optional[Tuple[int, int]]
    fact_type: str
    status: str = "explicit"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["source_span"] = list(self.source_span) if self.source_span is not None else None
        return payload


@dataclass
class CaseFactStructure:
    """Fact-only representation used by Baselines B and C."""

    parties: List[FactSpan] = field(default_factory=list)
    actors: List[FactSpan] = field(default_factory=list)
    entities: List[FactSpan] = field(default_factory=list)
    events: List[FactSpan] = field(default_factory=list)
    timeline: List[FactSpan] = field(default_factory=list)
    disputed_actions: List[FactSpan] = field(default_factory=list)
    procedural_actions: List[FactSpan] = field(default_factory=list)
    claims: List[FactSpan] = field(default_factory=list)
    requested_relief: List[FactSpan] = field(default_factory=list)
    explicit_facts: List[FactSpan] = field(default_factory=list)
    missing_facts: List[FactSpan] = field(default_factory=list)

    def all_items(self) -> List[FactSpan]:
        items: List[FactSpan] = []
        for name in self.field_names():
            items.extend(getattr(self, name))
        return items

    @classmethod
    def field_names(cls) -> Tuple[str, ...]:
        return (
            "parties",
            "actors",
            "entities",
            "events",
            "timeline",
            "disputed_actions",
            "procedural_actions",
            "claims",
            "requested_relief",
            "explicit_facts",
            "missing_facts",
        )

    def by_id(self) -> Dict[str, FactSpan]:
        return {item.fact_id: item for item in self.all_items()}

    def explicit_by_id(self) -> Dict[str, FactSpan]:
        return {
            item.fact_id: item
            for item in self.all_items()
            if item.status == "explicit" and item.source_span is not None
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            name: [item.to_dict() for item in getattr(self, name)]
            for name in self.field_names()
        }


@dataclass
class IssueProvenance:
    stage: str
    supporting_retrieval_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LegalIssue:
    """A question for legal analysis, not a legal conclusion."""

    issue_id: str
    question: str
    trigger_fact_ids: List[str]
    legal_concepts: List[str]
    issue_type: str
    importance: str
    confidence: str
    uncertainty_reason: Optional[str]
    query_seeds: List[str]
    provenance: IssueProvenance
    inferred_legal_concepts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["provenance"] = self.provenance.to_dict()
        return payload


@dataclass
class RetrievalResult:
    result_id: str
    query: str
    rank: int
    score: float
    doc_id: str
    chunk_id: str
    source_scope_id: str
    text_version_id: str
    span_start: int
    span_end: int
    title: str
    snippet: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalTrace:
    retrieval_id: str
    candidate_issue_id: str
    query: str
    results: List[RetrievalResult]
    corpus_version: str
    scope_mode: str
    excluded_doc_ids: List[str] = field(default_factory=list)
    indexed_doc_ids: List[str] = field(default_factory=list)
    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [item.to_dict() for item in self.results]
        return payload


@dataclass
class RefinementAction:
    action: str
    issue_id: Optional[str]
    source_issue_ids: List[str]
    question: Optional[str]
    reason: str
    supporting_retrieval_ids: List[str] = field(default_factory=list)
    accepted: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IssueSpottingResult:
    case_facts: DynamicCaseInput
    structured_facts: Optional[CaseFactStructure]
    candidate_issues: List[LegalIssue]
    retrieval_trace: List[RetrievalTrace]
    final_issues: List[LegalIssue]
    warnings: List[str]
    provenance: Dict[str, Any]
    refinement_actions: List[RefinementAction] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_facts": self.case_facts.to_dict(),
            "structured_facts": (
                self.structured_facts.to_dict() if self.structured_facts is not None else None
            ),
            "candidate_issues": [item.to_dict() for item in self.candidate_issues],
            "retrieval_trace": [item.to_dict() for item in self.retrieval_trace],
            "final_issues": [item.to_dict() for item in self.final_issues],
            "warnings": list(self.warnings),
            "provenance": self.provenance,
            "refinement_actions": [item.to_dict() for item in self.refinement_actions],
        }


@dataclass
class IssueSpottingConfig:
    """Runtime and experiment configuration; serialized into every run manifest."""

    method: str = "C"
    provider: str = "openrouter"
    model: str = "deepseek/deepseek-v4.1-flash"
    temperature: float = 0.0
    max_tokens: int = 12000
    timeout_seconds: int = 300
    http_retries: int = 3
    contract_retries: int = 2
    top_k: int = 6
    corpus_dir: str = "corpus_expansion/CV-0005"
    scope_mode: str = "shared_experimental"
    exclude_doc_ids: Tuple[str, ...] = ()
    prompt_dir: str = "prompts/issue_spotting"
    api_base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"
    api_key_path: str = "openrouter key.txt"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["exclude_doc_ids"] = list(self.exclude_doc_ids)
        return payload

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> "IssueSpottingConfig":
        if value is None:
            return cls()
        known = {field for field in cls.__dataclass_fields__}
        unknown = sorted(set(value) - known)
        if unknown:
            raise ValueError(f"unknown issue spotting config fields: {unknown}")
        payload = dict(value)
        if "exclude_doc_ids" in payload:
            payload["exclude_doc_ids"] = tuple(payload["exclude_doc_ids"])
        return cls(**payload)

    def corpus_path(self) -> Path:
        return Path(self.corpus_dir)
