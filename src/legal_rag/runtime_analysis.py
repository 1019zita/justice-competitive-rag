"""End-to-end runtime orchestration: issue spotting, planning, retrieval, G1."""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import replace
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .audit import AUDIT_VERSION, RuntimeAuditService
from .data import REPO_ROOT
from .issue_spotting import DynamicCaseInput, IssueSpottingConfig, spot_issues
from .issue_spotting.llm import ModelClient
from .issue_spotting.models import CaseFactStructure, LegalIssue
from .query_planning import DynamicQueryPlanner
from .query_planning.retrieval import (
    DynamicCompetitiveRetriever,
    DynamicRetrievedChunk,
    DynamicRetrievalTrace,
    RETRIEVAL_VERSION,
    RUNTIME_SCOPE_MODE,
    RUNTIME_SCOPE_NAME,
)
from .runtime_synthesis import RuntimeSynthesis


RUNTIME_VERSION = "LIVE_ANALYSIS_RUNTIME_V1"


class RuntimeAnalysisError(RuntimeError):
    """A live analysis could not produce a validated result."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RuntimeAnalysisService:
    def __init__(
        self,
        *,
        corpus_dir: str = "corpus_expansion/CV-0005",
        exclude_doc_ids: Sequence[str] = (),
        top_k_per_route: int = 2,
    ) -> None:
        self.corpus_dir = os.environ.get("LEGAL_RAG_CORPUS_PATH", corpus_dir)
        self.exclude_doc_ids = tuple(sorted(set(exclude_doc_ids)))
        self.top_k_per_route = max(1, top_k_per_route)
        self.planner = DynamicQueryPlanner()

    def analyze(
        self,
        *,
        facts: str,
        mode: str = "case-analysis",
        viewpoint: Optional[str] = None,
        question: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(facts, str) or len(facts.strip()) < 20:
            raise RuntimeAnalysisError("facts must contain at least 20 non-whitespace characters")
        if mode not in {"case-analysis", "viewpoint-check"}:
            raise RuntimeAnalysisError("mode must be case-analysis or viewpoint-check")
        if mode == "viewpoint-check" and not (viewpoint or "").strip():
            raise RuntimeAnalysisError("viewpoint is required for viewpoint-check")

        config = self._issue_config()
        client = ModelClient(config)
        issue_result = spot_issues(
            DynamicCaseInput(facts, source_label="runtime_api"),
            config=config,
            client=client,
        )
        if not issue_result.final_issues:
            raise RuntimeAnalysisError("issue spotting returned no final issues")

        query_plan = self.planner.plan(
            issue_result.structured_facts or CaseFactStructure(),
            issue_result.final_issues,
            mode=mode,
            viewpoint=viewpoint,
        )
        retriever = DynamicCompetitiveRetriever(
            corpus_dir=self.corpus_dir,
            top_k_per_route=self.top_k_per_route,
            exclude_doc_ids=self.exclude_doc_ids,
        )
        evidence, retrieval_traces = retriever.retrieve(query_plan)
        runtime_audit = RuntimeAuditService().audit(
            case_facts=facts,
            issues=issue_result.final_issues,
            evidence=evidence,
        )
        synthesis_config = replace(
            config,
            max_tokens=int(os.environ.get("LEGAL_RAG_G1_MAX_TOKENS", "5000")),
            contract_retries=2,
        )
        audit_results = {
            evidence_id: bundle.to_dict()
            for evidence_id, bundle in runtime_audit["bundles"].items()
        }
        synthesis = RuntimeSynthesis(ModelClient(synthesis_config))
        try:
            g1_payload, synthesis_provenance = synthesis.synthesize(
                case_facts=facts,
                structured_facts=issue_result.structured_facts or CaseFactStructure(),
                issues=issue_result.final_issues,
                evidence=evidence,
                viewpoint=viewpoint or "",
                audit_results=audit_results,
            )
        except Exception as audit_prompt_error:  # noqa: BLE001
            try:
                # Audit failure or audit-expanded prompt failure must not block RAG.
                g1_payload, synthesis_provenance = synthesis.synthesize(
                    case_facts=facts,
                    structured_facts=issue_result.structured_facts or CaseFactStructure(),
                    issues=issue_result.final_issues,
                    evidence=evidence,
                    viewpoint=viewpoint or "",
                    audit_results={},
                )
                synthesis_provenance = {
                    **synthesis_provenance,
                    "audit_prompt_fallback": True,
                    "audit_prompt_failure": str(audit_prompt_error),
                }
            except Exception as exc:  # noqa: BLE001
                raise RuntimeAnalysisError(f"live G1 synthesis failed: {exc}") from exc

        return self._adapt_result(
            facts=facts,
            mode=mode,
            viewpoint=viewpoint,
            question=question,
            issue_result=issue_result,
            query_plan=query_plan,
            evidence=evidence,
            retrieval_traces=retrieval_traces,
            g1_payload=g1_payload,
            synthesis_provenance=synthesis_provenance,
            audit_results=audit_results,
        )

    def _issue_config(self) -> IssueSpottingConfig:
        provider = os.environ.get("LEGAL_RAG_PROVIDER", "openrouter")
        model = os.environ.get("LEGAL_RAG_MODEL", "deepseek/deepseek-v4.1-flash")
        base_url = os.environ.get("LEGAL_RAG_BASE_URL", "https://openrouter.ai/api/v1")
        api_key_path = os.environ.get("LEGAL_RAG_API_KEY_PATH", "openrouter key.txt")
        return IssueSpottingConfig(
            method="B",
            provider=provider,
            model=model,
            temperature=0.0,
            max_tokens=int(os.environ.get("LEGAL_RAG_MAX_TOKENS", "12000")),
            timeout_seconds=60,
            http_retries=1,
            contract_retries=1,
            top_k=6,
            corpus_dir=self.corpus_dir,
            scope_mode=RUNTIME_SCOPE_MODE,
            exclude_doc_ids=self.exclude_doc_ids,
            api_base_url=base_url,
            api_key_path=api_key_path,
        )

    def _adapt_result(
        self,
        *,
        facts: str,
        mode: str,
        viewpoint: Optional[str],
        question: Optional[str],
        issue_result: Any,
        query_plan: Any,
        evidence: Sequence[DynamicRetrievedChunk],
        retrieval_traces: Sequence[DynamicRetrievalTrace],
        g1_payload: Mapping[str, Any],
        synthesis_provenance: Mapping[str, Any],
        audit_results: Mapping[str, Any],
    ) -> Dict[str, Any]:
        assessment_by_issue = {
            item.get("issue_id"): item.get("assessment", "")
            for item in (g1_payload.get("issue_assessments") or [])
            if isinstance(item, dict)
        }
        issues = [
            {
                "id": issue.issue_id,
                "title": issue.question,
                "description": assessment_by_issue.get(issue.issue_id) or self._issue_description(issue),
            }
            for issue in issue_result.final_issues
        ]
        evidence_by_id = {item.evidence_id: item for item in evidence}
        cited_claims: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        cited_ids = set()
        for claim in g1_payload.get("claims") or []:
            if not isinstance(claim, dict):
                continue
            claim_type = str(claim.get("claim_type") or "")
            for citation in claim.get("citations") or []:
                evidence_id = citation.get("evidence_id") if isinstance(citation, dict) else None
                if evidence_id in evidence_by_id:
                    cited_ids.add(evidence_id)
                    cited_claims[evidence_id].append(
                        {
                            "claim": claim,
                            "claim_type": claim_type,
                        }
                    )
        supporting: List[Dict[str, Any]] = []
        weakening: List[Dict[str, Any]] = []
        for evidence_id in sorted(cited_ids, key=self._evidence_sort_key(evidence_by_id)):
            item = evidence_by_id[evidence_id]
            claim_rows = cited_claims[evidence_id]
            directions = {row["claim_type"] for row in claim_rows}
            direction = "weakening" if "counter" in directions and "support" not in directions else "supporting"
            output = self._evidence_item(item, claim_rows, direction, audit_results.get(evidence_id, {}))
            if direction == "weakening":
                weakening.append(output)
            else:
                supporting.append(output)

        missing_facts = self._unresolved_facts(issue_result.structured_facts, g1_payload)
        gaps = [item.get("description", "") for item in (g1_payload.get("gaps") or []) if isinstance(item, dict)]
        warnings = list(issue_result.warnings)
        if synthesis_provenance.get("audit_prompt_fallback"):
            warnings.append("G1 used compact prompt fallback after audit-enriched prompt contract failure")
        if not evidence:
            warnings.append("shared corpus returned no retrieval chunks")
        if g1_payload.get("human_review", {}).get("required"):
            warnings.append(
                "G1 marked this analysis for human review; authority/applicability/evidence relation audits are unavailable"
            )
        coverage = self._coverage(evidence, cited_ids, gaps, retrieval_traces, audit_results)
        issue_provenance = issue_result.provenance
        return {
            "analysisId": f"AN-{uuid.uuid4().hex[:12]}",
            "mode": mode,
            "createdAt": _now(),
            "input": {"facts": facts, "question": question, "viewpoint": viewpoint},
            "canonicalArtifact": self._canonical_artifact(),
            "caseSummary": str(g1_payload.get("case_summary") or facts[:500]),
            "issues": issues,
            "overallAssessment": self._overall_assessment(g1_payload),
            "supportingEvidence": supporting,
            "weakeningEvidence": weakening,
            "alternativeExplanations": list(g1_payload.get("alternative_explanations") or []),
            "unresolvedFacts": missing_facts,
            "retrievalCoverage": coverage,
            "followUpSuggestions": list(g1_payload.get("follow_up_suggestions") or []),
            "runtimeWarnings": warnings,
            "runtimeProvenance": {
                "runtime_version": RUNTIME_VERSION,
                "input_contract": {
                    "raw_case_input": True,
                    "case_id_required": False,
                    "frozen_issue_input": False,
                    "frozen_hypothesis_input": False,
                    "prewritten_answer_input": False,
                },
                "issue_spotting": issue_provenance,
                "query_plan": query_plan.to_dict(),
                "retrieval": {
                    "algorithm": RETRIEVAL_VERSION,
                    "scope_name": RUNTIME_SCOPE_NAME,
                    "scope_mode": RUNTIME_SCOPE_MODE,
                    "corpus_version": "CV-0005",
                    "excluded_doc_ids": list(self.exclude_doc_ids),
                    "traces": [item.to_dict() for item in retrieval_traces],
                    "route_is_intent_not_evidence_relation": True,
                },
                "synthesis": {
                    "prompt_version": "G1_RUNTIME_V1",
                    "schema_version": "G1_RUNTIME_RESPONSE_V1",
                    "provenance": dict(synthesis_provenance),
                    "audit_version": AUDIT_VERSION,
                    "authority_audit": "runtime_mvp",
                    "applicability_audit": "runtime_mvp",
                    "evidence_relation_classifier": "unavailable",
                },
            },
        }

    @staticmethod
    def _issue_description(issue: LegalIssue) -> str:
        concepts = "、".join(issue.legal_concepts[:4])
        return f"类型：{issue.issue_type}；法律概念：{concepts or '待核实'}；置信度：{issue.confidence}。"

    @staticmethod
    def _evidence_sort_key(evidence_by_id: Mapping[str, DynamicRetrievedChunk]):
        return lambda evidence_id: (
            evidence_by_id[evidence_id].issue_id,
            evidence_by_id[evidence_id].retrieval_route,
            evidence_by_id[evidence_id].rank,
            evidence_id,
        )

    @staticmethod
    def _key_sentence(text: str) -> str:
        candidates = [part.strip() for part in re.split(r"(?<=[。！？!?；;])", text) if part.strip()]
        value = candidates[0] if candidates else text.strip()
        return value[:500]

    def _evidence_item(
        self,
        item: DynamicRetrievedChunk,
        claim_rows: Sequence[Mapping[str, Any]],
        direction: str,
        audit_bundle: Mapping[str, Any],
    ) -> Dict[str, Any]:
        claim_texts = [str(row["claim"].get("text") or "") for row in claim_rows if isinstance(row.get("claim"), dict)]
        relevance = "；".join(text for text in claim_texts if text) or "当前争点的实时检索材料。"
        issue_ids = sorted({item.issue_id} | {str(row["claim"].get("issue_id")) for row in claim_rows if isinstance(row.get("claim"), dict)})
        authority = audit_bundle.get("authority") or {}
        applicability = audit_bundle.get("applicability") or {}
        applicability_status = str(applicability.get("status") or "unavailable")
        applicability_level = {
            "directly_relevant": "high",
            "supportive_reference": "medium",
            "limited": "low",
            "uncertain": "low",
            "not_applicable": "low",
            "unavailable": "low",
        }.get(applicability_status, "low")
        applicability_provenance = (
            "verified"
            if applicability_status in {"directly_relevant", "supportive_reference", "limited", "not_applicable"}
            else "unavailable"
        )
        authority_status = str(authority.get("status") or "unavailable")
        return {
            "id": item.evidence_id,
            "issueIds": issue_ids,
            "direction": direction,
            "title": item.title or item.doc_id,
            "sourceType": item.document_type or "法律资料",
            "authorityLevel": authority.get("authority_level") or item.authority_tier or "unknown",
            "authorityReason": authority.get("reason") or "authority audit unavailable。",
            "sourceEvidenceStatus": "verified",
            "sourceEvidenceSource": "CV-0005 real retrieved chunk",
            "keySentence": self._key_sentence(item.text),
            "relevanceReason": relevance,
            "applicability": {
                "level": applicability_level,
                "reason": applicability.get("reason") or "applicability audit unavailable。",
                "status": applicability_provenance,
            },
            "authorityAudit": authority,
            "applicabilityAudit": applicability,
            "fullText": item.text,
            "source": {
                "origin": item.source_origin,
                "publisher": item.publisher,
                "url": item.source_url,
                "documentId": item.doc_id,
                "publicationDate": item.publication_date,
            },
            "retrievalProvenance": {
                "status": "verified",
                "query": item.query,
                "rank": item.rank,
                "score": item.score,
                "chunkId": item.chunk_id,
                "retrievalChannel": "tfidf_char",
                "authorityAudit": authority.get("reason") or authority_status,
                "authorityAuditStatus": "verified" if authority_status in {"verified", "plausible"} else "unavailable",
                "applicabilityAudit": applicability.get("reason") or applicability_status,
                "applicabilityAuditStatus": applicability_provenance,
                "retrievalRoute": item.retrieval_route,
            },
        }

    @staticmethod
    def _unresolved_facts(structured: Optional[CaseFactStructure], payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        seen = set()
        for item in (structured.missing_facts if structured else []):
            key = item.text.strip()
            if key and key not in seen:
                seen.add(key)
                rows.append({"id": item.fact_id, "fact": key, "whyItMatters": item.notes or "可能影响后续法律分析。", "severity": "high"})
        for index, item in enumerate(payload.get("unresolved_facts") or [], start=1):
            if not isinstance(item, dict):
                continue
            fact = str(item.get("fact") or "").strip()
            if fact and fact not in seen:
                seen.add(fact)
                rows.append({"id": f"GAP-{index:03d}", "fact": fact, "whyItMatters": str(item.get("why_it_matters") or "影响当前分析边界。"), "severity": "medium"})
        return rows

    @staticmethod
    def _overall_assessment(payload: Mapping[str, Any]) -> Dict[str, Any]:
        value = payload.get("overall_assessment") or {}
        return {
            "summary": str(value.get("summary") or "当前证据不足以形成完整判断。"),
            "strength": value.get("strength") if value.get("strength") in {"strong", "moderate", "mixed", "insufficient"} else "insufficient",
            "uncertaintySummary": str(value.get("uncertainty_summary") or "审计字段尚未执行。"),
        }

    @staticmethod
    def _coverage(
        evidence: Sequence[DynamicRetrievedChunk],
        cited_ids: set[str],
        gaps: Sequence[str],
        traces: Sequence[DynamicRetrievalTrace],
        audit_results: Mapping[str, Any],
    ) -> Dict[str, Any]:
        source_counts = Counter(item.document_type or "法律资料" for item in evidence)
        dates = sorted({item.publication_date for item in evidence if item.publication_date})
        time_range = f"{dates[0]} – {dates[-1]}" if dates else "未提供"
        authority_verified = sum(
            1 for bundle in audit_results.values()
            if (bundle.get("authority") or {}).get("status") == "verified"
        )
        applicability_passed = sum(
            1 for bundle in audit_results.values()
            if (bundle.get("applicability") or {}).get("status") in {"directly_relevant", "supportive_reference"}
        )
        authority_unknown = sum(
            1 for bundle in audit_results.values()
            if (bundle.get("authority") or {}).get("status") in {"unknown", "unavailable"}
        )
        applicability_unknown = sum(
            1 for bundle in audit_results.values()
            if (bundle.get("applicability") or {}).get("status") in {"uncertain", "unavailable"}
        )
        known_gaps = list(gaps)
        if any(not trace.result_ids for trace in traces):
            known_gaps.append("至少一个动态检索意图没有返回 chunk")
        if authority_unknown:
            known_gaps.append(f"{authority_unknown} 条 evidence 的 authority 状态未知或不可用")
        if applicability_unknown:
            known_gaps.append(f"{applicability_unknown} 条 evidence 的 applicability 状态未知或不可用")
        known_gaps.append("evidence relation classifier unavailable")
        provenance = {
            "sourceCounts": {"status": "verified", "source": "live CV-0005 retrieval"},
            "candidateCount": {"status": "verified", "source": "live retrieval trace"},
            "authorityPassedCount": {"status": "verified" if audit_results else "unavailable", "source": "runtime authority audit"},
            "applicabilityPassedCount": {"status": "verified" if audit_results else "unavailable", "source": "runtime applicability audit"},
            "citedCount": {"status": "verified", "source": "validated live G1 citations"},
            "timeRange": {"status": "verified" if dates else "unavailable", "source": "CV-0005 document metadata"},
            "coveredSources": {"status": "verified", "source": "live retrieval results"},
            "knownGaps": {"status": "verified", "source": "runtime audit summary"},
        }
        return {
            "sourceCounts": dict(source_counts),
            "candidateCount": len(evidence),
            "authorityPassedCount": authority_verified,
            "applicabilityPassedCount": applicability_passed,
            "citedCount": len(cited_ids),
            "timeRange": time_range,
            "coveredSources": sorted({item.source_origin for item in evidence if item.source_origin}),
            "knownGaps": known_gaps,
            "provenance": provenance,
        }

    @staticmethod
    def _canonical_artifact() -> Dict[str, Any]:
        no = "NO"
        return {
            "version": "CV-0005",
            "sourcePaths": [
                "corpus_expansion/CV-0005/manifest.json",
                "corpus_expansion/CV-0005/documents.json",
                "corpus_expansion/CV-0005/chunks/",
            ],
            "contentHashEquivalent": {
                "hg2_0004": {"vignetteManifest": no, "keySentenceAudit": no, "conditionArtifacts": no},
                "hg2_0003": {"vignetteManifest": no, "keySentenceAudit": no, "conditionArtifacts": no},
            },
        }


__all__ = ["RuntimeAnalysisError", "RuntimeAnalysisService", "RUNTIME_VERSION"]
