from __future__ import annotations

import unittest

from src.legal_rag.audit import RuntimeAuditService
from src.legal_rag.audit.applicability import audit_applicability
from src.legal_rag.audit.authority import audit_authority
from src.legal_rag.issue_spotting.models import IssueProvenance, LegalIssue
from src.legal_rag.query_planning.retrieval import DynamicRetrievedChunk


def evidence(**overrides):
    payload = {
        "evidence_id": "EV-0001",
        "issue_id": "ISS-001",
        "retrieval_id": "R-001",
        "query_id": "Q-001",
        "query": "退学处理 行政程序",
        "retrieval_route": "neutral",
        "rank": 1,
        "score": 0.4,
        "doc_id": "DOC-001",
        "chunk_id": "DOC-001-C0001",
        "source_scope_id": "SRC-AUTH-CASE01-01",
        "text_version_id": "TV-001",
        "title": "高校退学处理行政程序案例",
        "source_origin": "最高人民法院",
        "source_url": None,
        "publication_date": "2022-01-01",
        "document_type": "指导性案例",
        "document_type_as_written": "指导性案例",
        "authority_role": "source_authority",
        "authority_tier": "unknown",
        "publisher": "最高人民法院",
        "source_database": None,
        "validity_status": "in_force",
        "jurisdiction": "中国大陆",
        "text": "退学处理应当遵循行政程序，学校应当保障学生陈述申辩。",
    }
    payload.update(overrides)
    return DynamicRetrievedChunk(**payload)


class RuntimeAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.issue = LegalIssue(
            issue_id="ISS-001",
            question="高校退学处理是否需要遵循行政程序？",
            trigger_fact_ids=["F-001"],
            legal_concepts=["行政程序", "退学处理"],
            issue_type="procedural",
            importance="high",
            confidence="medium",
            uncertainty_reason=None,
            query_seeds=["退学处理 行政程序"],
            provenance=IssueProvenance("initial"),
        )

    def test_explicit_publisher_can_be_verified(self):
        result = audit_authority(evidence())
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.publisher, "最高人民法院")
        self.assertNotEqual(result.authority_level, "unknown")

    def test_host_is_not_promoted_to_publisher(self):
        result = audit_authority(evidence(publisher=None, source_origin="商业数据库", source_database="商业数据库"))
        self.assertNotEqual(result.status, "verified")
        self.assertIsNone(result.publisher)
        self.assertIn("host", result.reason)

    def test_applicability_preserves_screening_limits(self):
        item = evidence()
        authority = audit_authority(item)
        result = audit_applicability(case_facts="学校作出退学处理。", issue=self.issue, item=item, authority=authority)
        self.assertIn(result.status, {"directly_relevant", "supportive_reference", "uncertain"})
        self.assertEqual(result.jurisdiction_fit, "fit")
        self.assertEqual(result.temporal_fit, "fit")
        self.assertNotIn("conclusion", result.reason)

    def test_unknown_metadata_is_preserved(self):
        item = evidence(publisher=None, jurisdiction="unknown", publication_date=None, validity_status="unknown")
        authority = audit_authority(item)
        applicability = audit_applicability(case_facts="新案件事实", issue=self.issue, item=item, authority=authority)
        self.assertIn(authority.status, {"plausible", "unknown"})
        self.assertEqual(authority.validity_status, "unknown")
        self.assertEqual(applicability.jurisdiction_fit, "unknown")
        self.assertEqual(applicability.temporal_fit, "not_assessed")

    def test_audit_failure_does_not_block_runtime_contract(self):
        result = RuntimeAuditService().audit(case_facts="事实", issues=[], evidence=[evidence()])
        self.assertFalse(result["blocks_rag"])
        self.assertEqual(result["failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
