from __future__ import annotations

import unittest

from src.legal_rag.issue_spotting.models import CaseFactStructure, FactSpan, IssueProvenance, LegalIssue
from src.legal_rag.query_planning import DynamicQueryPlanner
from src.legal_rag.query_planning.retrieval import DynamicCompetitiveRetriever
from src.legal_rag.runtime_synthesis import RuntimeSynthesis


class RuntimePlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = CaseFactStructure(
            explicit_facts=[FactSpan("F-001", "学校作出退学处理。", (0, 10), "event")]
        )
        self.issue = LegalIssue(
            issue_id="ISS-001",
            question="该退学处理是否需要满足程序要求？",
            trigger_fact_ids=["F-001"],
            legal_concepts=["行政程序"],
            issue_type="procedural",
            importance="high",
            confidence="medium",
            uncertainty_reason=None,
            query_seeds=["退学处理 程序"],
            provenance=IssueProvenance("initial"),
        )

    def test_planner_uses_current_issue_and_viewpoint(self):
        plan = DynamicQueryPlanner().plan(
            self.facts,
            [self.issue],
            mode="viewpoint-check",
            viewpoint="学校没有履行听取申辩程序",
        )
        self.assertEqual([item.route for item in plan.issue_plans[0].queries], ["neutral", "support", "counter"])
        self.assertIn("学校没有履行听取申辩程序", plan.issue_plans[0].queries[1].query)
        self.assertNotIn("CASE-01", plan.issue_plans[0].queries[0].query)
        self.assertTrue(all(item.planner_version == "DYNAMIC_QUERY_PLANNER_V1" for item in plan.issue_plans[0].queries))

    def test_shared_retrieval_records_real_scope_and_exclusion(self):
        retriever = DynamicCompetitiveRetriever(corpus_dir="data/sample_corpus", top_k_per_route=1, exclude_doc_ids=["DOC-SAMPLE-0001"])
        plan = DynamicQueryPlanner().plan(self.facts, [self.issue])
        evidence, traces = retriever.retrieve(plan)
        self.assertEqual(len(traces), 3)
        self.assertTrue(all(trace.scope_mode == "shared_runtime" for trace in traces))
        self.assertTrue(all(item.doc_id != "DOC-SAMPLE-0001" for item in evidence))
        self.assertTrue(all(item.score >= 0 for item in evidence))


class RuntimeSynthesisContractTests(unittest.TestCase):
    def test_unknown_evidence_citation_is_rejected(self):
        issue = LegalIssue(
            issue_id="ISS-001",
            question="问题？",
            trigger_fact_ids=["F-001"],
            legal_concepts=["程序"],
            issue_type="procedural",
            importance="high",
            confidence="medium",
            uncertainty_reason=None,
            query_seeds=["程序"],
            provenance=IssueProvenance("initial"),
        )
        payload = {
            "case_summary": "摘要",
            "issue_assessments": [{"issue_id": "ISS-001", "assessment": "待分析"}],
            "overall_assessment": {"summary": "不确定", "strength": "insufficient", "uncertainty_summary": "缺证据"},
            "claims": [{
                "claim_id": "CL-001", "issue_id": "ISS-001", "claim_type": "boundary",
                "text": "命题", "support_status": "insufficient", "citations": [{"evidence_id": "EV-X"}],
            }],
            "alternative_explanations": [],
            "unresolved_facts": [],
            "gaps": [{"route": "neutral", "description": "缺证据"}],
            "follow_up_suggestions": [],
            "human_review": {"required": True, "reason": "缺证据"},
        }
        with self.assertRaises(Exception):
            RuntimeSynthesis._validate(payload, [issue], [])


if __name__ == "__main__":
    unittest.main()
