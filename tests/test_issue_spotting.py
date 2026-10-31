from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.legal_rag.issue_spotting.broad_retrieval import BroadSparseRetriever
from src.legal_rag.issue_spotting.models import (
    CaseFactStructure,
    DynamicCaseInput,
    FactSpan,
    IssueProvenance,
    IssueSpottingConfig,
    LegalIssue,
    RefinementAction,
)
from src.legal_rag.issue_spotting.service import spot_issues
from src.legal_rag.issue_spotting.fact_structurer import _deterministic_explicit_facts
from src.legal_rag.issue_spotting.validators import (
    ContractError,
    parse_fact_structure,
    parse_issue_payload,
)


class FakeClient:
    """Contract-valid stage responses; no model call or fake runtime fallback."""

    def __init__(self, raw_facts: str) -> None:
        self.raw_facts = raw_facts
        self.fact = FactSpan(
            fact_id="F-001",
            text=raw_facts,
            source_span=(0, len(raw_facts)),
            fact_type="event",
            status="explicit",
        )

    def call_json(self, prompt, validator, *, prompt_version, stage):
        facts = CaseFactStructure(explicit_facts=[self.fact])
        issue = LegalIssue(
            issue_id="ISS-001",
            question="该处分是否需要满足相应程序要求？",
            trigger_fact_ids=["F-001"],
            legal_concepts=["程序要求"],
            inferred_legal_concepts=["程序要求"],
            issue_type="procedural",
            importance="high",
            confidence="medium",
            uncertainty_reason=None,
            query_seeds=["处分程序要求"],
            provenance=IssueProvenance(stage="retrieval_refined" if stage == "retrieval_refinement" else "initial"),
        )
        if stage == "fact_structure":
            return facts, {"stage": stage}, "{}", {}
        if stage in {"candidate_issue_spotting", "structured_issue_spotting", "single_pass_issue_spotting"}:
            return [issue], {"stage": stage}, "{}", {}
        if stage == "retrieval_refinement":
            return ([], [issue]), {"stage": stage}, "{}", {}
        raise AssertionError(stage)


class IssueSpottingTests(unittest.TestCase):
    def test_fact_span_grounding(self):
        raw = "甲方于2024年签约。"
        payload = {
            "parties": [],
            "actors": [],
            "entities": [],
            "events": [
                {
                    "fact_id": "F-001",
                    "text": raw,
                    "source_span": [0, len(raw)],
                    "fact_type": "event",
                    "status": "explicit",
                    "notes": "",
                }
            ],
            "timeline": [],
            "disputed_actions": [],
            "procedural_actions": [],
            "claims": [],
            "requested_relief": [],
            "explicit_facts": [],
            "missing_facts": [
                {
                    "fact_id": "M-001",
                    "text": "是否实际履行",
                    "source_span": None,
                    "fact_type": "missing",
                    "status": "unknown",
                    "notes": "原文没有说明",
                }
            ],
        }
        structure = parse_fact_structure(payload, raw)
        self.assertEqual(structure.events[0].source_span, (0, len(raw)))
        bad = json.loads(json.dumps(payload, ensure_ascii=False))
        bad["events"][0]["text"] = "不存在原文"
        bad["events"][0]["source_span"] = [0, 5]
        with self.assertRaises(ContractError):
            parse_fact_structure(bad, raw)
    def test_deterministic_fact_fallback_is_exactly_grounded(self):
        raw = "甲方签约；乙方付款。"
        structure = _deterministic_explicit_facts(raw)
        self.assertEqual([fact.text for fact in structure.explicit_facts], ["甲方签约；", "乙方付款。"])
        for fact in structure.explicit_facts:
            start, end = fact.source_span
            self.assertEqual(raw[start:end], fact.text)
            self.assertEqual(fact.notes, "deterministic_raw_span_fallback")


    def test_no_frozen_issue_dependency(self):
        prompt_root = Path("prompts/issue_spotting")
        prompt_text = "\n".join(path.read_text(encoding="utf-8") for path in prompt_root.glob("*.txt"))
        self.assertNotIn("CASE-01-ISS", prompt_text)
        self.assertNotIn("CASE-02-ISS", prompt_text)
        self.assertNotIn("CASE-03-ISS", prompt_text)
        self.assertNotIn("CASE-01-H", prompt_text)
        self.assertNotIn("CASE-02-H", prompt_text)
        self.assertNotIn("CASE-03-H", prompt_text)

    def test_no_case_id_dependency(self):
        raw = "学校作出退学处分。"
        result = spot_issues(
            DynamicCaseInput(raw),
            config=IssueSpottingConfig(method="A"),
            client=FakeClient(raw),
        )
        self.assertFalse(result.provenance["input_contract"]["case_id_required"])
        self.assertTrue(result.provenance["input_contract"]["frozen_issue_input"] is False)
        self.assertEqual(result.final_issues[0].issue_id, "ISS-001")

    def test_issue_schema_validation(self):
        raw = "学校作出退学处分。"
        facts = CaseFactStructure(
            explicit_facts=[
                FactSpan("F-001", raw, (0, len(raw)), "event", "explicit")
            ]
        )
        payload = {
            "issues": [
                {
                    "issue_id": "ISS-001",
                    "question": "该处分是否需要满足相应程序要求？",
                    "trigger_fact_ids": ["F-001"],
                    "legal_concepts": ["程序要求"],
                    "inferred_legal_concepts": ["程序要求"],
                    "issue_type": "procedural",
                    "importance": "high",
                    "confidence": "medium",
                    "uncertainty_reason": None,
                    "query_seeds": ["处分程序"],
                    "provenance": {"stage": "initial", "supporting_retrieval_ids": []},
                }
            ]
        }
        issues = parse_issue_payload(payload, facts)
        self.assertEqual(issues[0].trigger_fact_ids, ["F-001"])
        self.assertEqual(issues[0].provenance.stage, "initial")
    def test_inferred_concepts_are_explicit_but_not_duplicated(self):
        raw = "学校作出退学处分。"
        facts = CaseFactStructure(
            explicit_facts=[FactSpan("F-001", raw, (0, len(raw)), "event", "explicit")]
        )
        payload = {
            "issues": [
                {
                    "issue_id": "ISS-001",
                    "question": "该处分是否需要满足相应程序要求？",
                    "trigger_fact_ids": ["F-001"],
                    "legal_concepts": ["程序审查"],
                    "inferred_legal_concepts": ["高校处分程序"],
                    "issue_type": "procedural",
                    "importance": "high",
                    "confidence": "medium",
                    "uncertainty_reason": None,
                    "query_seeds": ["处分程序"],
                    "provenance": {"stage": "initial", "supporting_retrieval_ids": []},
                }
            ]
        }
        issues = parse_issue_payload(payload, facts)
        self.assertEqual(issues[0].inferred_legal_concepts, ["高校处分程序"])
        bad = json.loads(json.dumps(payload, ensure_ascii=False))
        bad["issues"][0]["legal_concepts"] = ["已经违法"]
        with self.assertRaises(ContractError):
            parse_issue_payload(bad, facts)


    def test_duplicate_issue_detection(self):
        raw = "学校作出退学处分。"
        facts = CaseFactStructure(
            explicit_facts=[FactSpan("F-001", raw, (0, len(raw)), "event", "explicit")]
        )
        issue = {
            "issue_id": "ISS-001",
            "question": "该处分是否需要满足相应程序要求？",
            "trigger_fact_ids": ["F-001"],
            "legal_concepts": ["程序要求"],
            "inferred_legal_concepts": ["程序要求"],
            "issue_type": "procedural",
            "importance": "high",
            "confidence": "medium",
            "uncertainty_reason": None,
            "query_seeds": ["处分程序"],
            "provenance": {"stage": "initial", "supporting_retrieval_ids": []},
        }
        with self.assertRaises(ContractError):
            parse_issue_payload({"issues": [issue, dict(issue)]}, facts)

    def test_issue_requires_trigger_fact(self):
        raw = "学校作出退学处分。"
        facts = CaseFactStructure(
            explicit_facts=[FactSpan("F-001", raw, (0, len(raw)), "event", "explicit")]
        )
        payload = {
            "issues": [
                {
                    "issue_id": "ISS-001",
                    "question": "是否存在另一个法律问题？",
                    "trigger_fact_ids": [],
                    "legal_concepts": ["概念"],
                    "inferred_legal_concepts": ["概念"],
                    "issue_type": "unknown",
                    "importance": "low",
                    "confidence": "low",
                    "uncertainty_reason": "没有事实触发",
                    "query_seeds": ["概念"],
                    "provenance": {"stage": "initial", "supporting_retrieval_ids": []},
                }
            ]
        }
        with self.assertRaises(ContractError):
            parse_issue_payload(payload, facts)

    def test_target_doc_exclusion(self):
        all_retriever = BroadSparseRetriever(
            "data/sample_corpus",
            scope_mode="shared_experimental",
            top_k=3,
        )
        excluded = all_retriever.snapshot.chunks[0].doc_id
        retriever = BroadSparseRetriever(
            "data/sample_corpus",
            scope_mode="shared_experimental",
            top_k=3,
            exclude_doc_ids=[excluded],
        )
        trace = retriever.search(
            retrieval_id="IR-TEST",
            candidate_issue_id="ISS-001",
            query="正当防卫 不法侵害",
        )
        self.assertNotIn(excluded, {item.doc_id for item in trace.results})
        self.assertNotIn(excluded, trace.indexed_doc_ids)
        self.assertEqual(trace.scope_mode, "shared_experimental")
        self.assertEqual(trace.excluded_doc_ids, [excluded])

    def test_retrieval_refinement_trace(self):
        raw = "学校作出退学处分。"
        result = spot_issues(
            DynamicCaseInput(raw),
            config=IssueSpottingConfig(method="C", top_k=2, corpus_dir="data/sample_corpus"),
            client=FakeClient(raw),
        )
        self.assertTrue(result.retrieval_trace)
        self.assertEqual(result.retrieval_trace[0].scope_mode, "shared_experimental")
        self.assertEqual(result.provenance["retrieval_contract"]["retrieval_is_coverage_check_only"], True)
        self.assertEqual(result.refinement_actions, [])


if __name__ == "__main__":
    unittest.main()
