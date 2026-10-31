"""Attach independent authority/applicability screening without blocking RAG."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

from ..issue_spotting.models import LegalIssue
from ..query_planning.retrieval import DynamicRetrievedChunk
from .applicability import audit_applicability
from .authority import audit_authority
from .models import EvidenceAuditBundle


AUDIT_VERSION = "RUNTIME_AUDIT_MVP_V1"


class RuntimeAuditService:
    def audit(
        self,
        *,
        case_facts: str,
        issues: Sequence[LegalIssue],
        evidence: Sequence[DynamicRetrievedChunk],
    ) -> Dict[str, Any]:
        issue_by_id = {issue.issue_id: issue for issue in issues}
        bundles: Dict[str, EvidenceAuditBundle] = {}
        failures = []
        for item in evidence:
            try:
                authority = audit_authority(item)
                issue = issue_by_id.get(item.issue_id)
                if issue is None:
                    raise ValueError(f"unknown issue_id {item.issue_id}")
                applicability = audit_applicability(
                    case_facts=case_facts,
                    issue=issue,
                    item=item,
                    authority=authority,
                )
                bundles[item.evidence_id] = EvidenceAuditBundle(
                    evidence_id=item.evidence_id,
                    authority=authority,
                    applicability=applicability,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{item.evidence_id}: {type(exc).__name__}")
                # The individual helpers are fail-safe; this branch protects the
                # whole runtime if a future adapter violates that contract.
                authority = audit_authority(item)
                issue = issue_by_id.get(item.issue_id)
                if issue is not None:
                    applicability = audit_applicability(
                        case_facts=case_facts,
                        issue=issue,
                        item=item,
                        authority=authority,
                    )
                    bundles[item.evidence_id] = EvidenceAuditBundle(
                        evidence_id=item.evidence_id,
                        authority=authority,
                        applicability=applicability,
                    )
        return {
            "version": AUDIT_VERSION,
            "method": "metadata_rules_only",
            "bundles": bundles,
            "failure_count": len(failures),
            "failures": failures,
            "blocks_rag": False,
        }


__all__ = ["AUDIT_VERSION", "RuntimeAuditService"]
