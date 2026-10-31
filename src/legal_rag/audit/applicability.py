"""Conservative issue/evidence applicability screening."""
from __future__ import annotations

import re
from typing import Iterable, List, Set

from ..issue_spotting.models import LegalIssue
from ..query_planning.retrieval import DynamicRetrievedChunk
from .models import ApplicabilityAuditResult, AuthorityAuditResult


def _terms(text: str) -> Set[str]:
    value = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text or "").lower()
    pieces = [part for part in value.split() if len(part) >= 2]
    cjk = {value[index : index + 2] for index in range(max(0, len(value) - 1)) if "\u4e00" <= value[index] <= "\u9fff" and "\u4e00" <= value[index + 1] <= "\u9fff"}
    return set(pieces) | cjk


def _fit(value: str | None, *, expected: Iterable[str]) -> str:
    if not value or value in {"UNKNOWN", "unknown", "未提供", "未核查"}:
        return "unknown"
    normalized = value.lower()
    if any(token in normalized for token in expected):
        return "fit"
    return "mismatch"


def audit_applicability(
    *,
    case_facts: str,
    issue: LegalIssue,
    item: DynamicRetrievedChunk,
    authority: AuthorityAuditResult,
) -> ApplicabilityAuditResult:
    try:
        issue_terms = _terms(" ".join([issue.question, *issue.legal_concepts, *issue.query_seeds]))
        evidence_terms = _terms(" ".join([item.title, item.text]))
        overlap = len(issue_terms & evidence_terms)
        issue_relevance = "fit" if overlap >= 3 else "unknown" if overlap else "mismatch"
        jurisdiction_fit = _fit(
            getattr(item, "jurisdiction", None),
            expected=("中国", "大陆", "全国", "china", "mainland"),
        )
        temporal_fit = "fit" if getattr(item, "publication_date", None) else "not_assessed"
        factual_terms = _terms(case_facts)
        factual_overlap = len(factual_terms & evidence_terms)
        factual_legal_fit = "fit" if factual_overlap >= 2 or overlap >= 3 else "unknown"

        if issue_relevance == "mismatch":
            status = "not_applicable"
            reason = "证据文本与当前争点的可见术语重叠不足；仅作为检索候选保留。"
        elif issue_relevance == "fit" and authority.status == "verified" and jurisdiction_fit == "fit" and temporal_fit == "fit":
            status = "directly_relevant"
            reason = "当前争点、法域、时间 metadata 与证据内容均有可见匹配；仍不是终局法律判断。"
        elif issue_relevance == "fit" or factual_legal_fit == "fit":
            status = "supportive_reference"
            reason = "证据与当前争点或事实具有参考性匹配，但至少一个法域/时间/权威维度未确认。"
        else:
            status = "uncertain"
            reason = "存在部分词汇或事实线索，但不足以确认直接适用。"
        fields = ["issue.question", "issue.legal_concepts", "evidence.title", "evidence.text"]
        if getattr(item, "jurisdiction", None):
            fields.append("jurisdiction")
        if getattr(item, "publication_date", None):
            fields.append("publication_date")
        return ApplicabilityAuditResult(
            status=status,
            issue_relevance=issue_relevance,
            jurisdiction_fit=jurisdiction_fit,
            temporal_fit=temporal_fit,
            factual_legal_fit=factual_legal_fit,
            reason=reason,
            provenance_fields=fields,
        )
    except Exception as exc:  # noqa: BLE001
        return ApplicabilityAuditResult(
            status="unavailable",
            issue_relevance="unknown",
            jurisdiction_fit="unknown",
            temporal_fit="not_assessed",
            factual_legal_fit="unknown",
            reason=f"applicability audit unavailable: {type(exc).__name__}",
            provenance_fields=[],
        )


__all__ = ["audit_applicability"]
