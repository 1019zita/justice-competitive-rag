"""Independent live G1-style synthesis for the product runtime."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from .data import REPO_ROOT
from .issue_spotting.llm import ModelClient
from .issue_spotting.models import CaseFactStructure, LegalIssue
from .issue_spotting.prompts import PromptRepository
from .issue_spotting.validators import ContractError
from .query_planning.retrieval import DynamicRetrievedChunk


RUNTIME_G1_PROMPT_VERSION = "G1_RUNTIME_V1"
RUNTIME_G1_SCHEMA_VERSION = "G1_RUNTIME_RESPONSE_V1"
RUNTIME_PROMPT_DIR = REPO_ROOT / "prompts" / "runtime"


class RuntimeSynthesis:
    def __init__(self, client: ModelClient) -> None:
        self.client = client
        self.prompts = PromptRepository(RUNTIME_PROMPT_DIR)

    def synthesize(
        self,
        *,
        case_facts: str,
        structured_facts: CaseFactStructure,
        issues: Sequence[LegalIssue],
        evidence: Sequence[DynamicRetrievedChunk],
        viewpoint: str = "",
        audit_results: Mapping[str, Any] | None = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        prompt = self.prompts.render(
            RUNTIME_G1_PROMPT_VERSION,
            {
                "CASE_FACTS": case_facts,
                "STRUCTURED_FACTS": json.dumps(structured_facts.to_dict(), ensure_ascii=False, indent=2),
                "ISSUES": json.dumps([issue.to_dict() for issue in issues], ensure_ascii=False, indent=2),
                "VIEWPOINT": viewpoint or "（未提供用户观点；请保持中性）",
                "EVIDENCE": self._render_evidence(evidence, audit_results or {}),
            },
        )
        value, provenance, _, _ = self.client.call_json(
            prompt,
            lambda payload: self._validate(payload, issues, evidence),
            prompt_version=RUNTIME_G1_PROMPT_VERSION,
            stage="runtime_g1_synthesis",
        )
        return value, provenance

    @staticmethod
    def _render_evidence(
        evidence: Sequence[DynamicRetrievedChunk],
        audit_results: Mapping[str, Any],
    ) -> str:
        blocks = []
        for item in evidence:
            text = item.text.strip()
            excerpt = text[:500]
            if len(text) > len(excerpt):
                excerpt += "……（原文仍保留在运行结果中）"
            blocks.append(
                json.dumps(
                    {
                        "evidence_id": item.evidence_id,
                        "issue_id": item.issue_id,
                        "retrieval_route": item.retrieval_route,
                        "query": item.query,
                        "rank": item.rank,
                        "score": item.score,
                        "doc_id": item.doc_id,
                        "chunk_id": item.chunk_id,
                        "title": item.title,
                        "source_origin": item.source_origin,
                        "source_url": item.source_url,
                        "authority_audit": audit_results.get(item.evidence_id, {}).get("authority"),
                        "applicability_audit": audit_results.get(item.evidence_id, {}).get("applicability"),
                        "excerpt": excerpt,
                    },
                    ensure_ascii=False,
                )
            )
        return "\n".join(blocks) if blocks else "（本次检索没有返回材料）"

    @staticmethod
    def _validate(
        payload: Any,
        issues: Sequence[LegalIssue],
        evidence: Sequence[DynamicRetrievedChunk],
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ContractError("runtime G1 response must be an object")
        required = (
            "case_summary",
            "issue_assessments",
            "overall_assessment",
            "claims",
            "alternative_explanations",
            "unresolved_facts",
            "gaps",
            "follow_up_suggestions",
            "human_review",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise ContractError(f"runtime G1 missing fields: {missing}")
        issue_ids = {issue.issue_id for issue in issues}
        evidence_ids = {item.evidence_id for item in evidence}
        assessments = payload.get("issue_assessments")
        if not isinstance(assessments, list):
            raise ContractError("runtime G1 issue_assessments must be a list")
        for item in assessments:
            if not isinstance(item, dict) or item.get("issue_id") not in issue_ids or not item.get("assessment"):
                raise ContractError("runtime G1 issue_assessments contains invalid issue")
        claims = payload.get("claims")
        if not isinstance(claims, list) or not claims:
            raise ContractError("runtime G1 claims must be a non-empty list")
        claim_ids = set()
        allowed_claim_types = {"governing_rule", "support", "counter", "boundary", "distinguishable", "neutral_background"}
        allowed_status = {"supported", "contradicted", "insufficient"}
        for claim in claims:
            if not isinstance(claim, dict):
                raise ContractError("runtime G1 claim must be an object")
            claim_id = claim.get("claim_id")
            if not claim_id or claim_id in claim_ids:
                raise ContractError(f"runtime G1 duplicate/empty claim_id: {claim_id}")
            claim_ids.add(claim_id)
            if claim.get("issue_id") not in issue_ids:
                raise ContractError(f"runtime G1 claim references unknown issue: {claim.get('issue_id')}")
            if claim.get("claim_type") not in allowed_claim_types:
                raise ContractError(f"runtime G1 invalid claim_type: {claim.get('claim_type')}")
            if claim.get("support_status") not in allowed_status:
                raise ContractError(f"runtime G1 invalid support_status: {claim.get('support_status')}")
            citations = claim.get("citations")
            if not isinstance(citations, list) or not citations:
                raise ContractError(f"runtime G1 claim has no citations: {claim_id}")
            for citation in citations:
                if not isinstance(citation, dict) or citation.get("evidence_id") not in evidence_ids:
                    raise ContractError(f"runtime G1 claim has unknown evidence citation: {claim_id}")
        assessment = payload.get("overall_assessment")
        if not isinstance(assessment, dict) or assessment.get("strength") not in {"strong", "moderate", "mixed", "insufficient"}:
            raise ContractError("runtime G1 overall_assessment is invalid")
        for gap in payload.get("gaps") or []:
            if not isinstance(gap, dict) or gap.get("route") not in {"neutral", "support", "counter"} or not gap.get("description"):
                raise ContractError("runtime G1 gap is invalid")
        review = payload.get("human_review")
        if not isinstance(review, dict) or not isinstance(review.get("required"), bool):
            raise ContractError("runtime G1 human_review is invalid")
        return payload


__all__ = ["RuntimeSynthesis", "RUNTIME_G1_PROMPT_VERSION", "RUNTIME_G1_SCHEMA_VERSION"]
