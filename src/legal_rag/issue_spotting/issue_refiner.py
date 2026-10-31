"""Candidate issue refinement from bounded-corpus coverage feedback."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence, Set, Tuple

from .broad_retrieval import render_retrieval_summary
from .llm import ModelClient
from .models import (
    CaseFactStructure,
    LegalIssue,
    RefinementAction,
    RetrievalTrace,
)
from .prompts import PromptRepository
from .validators import parse_refinement_payload


class IssueRefiner:
    prompt_version = "ISSUE_REFINE_WITH_RETRIEVAL_V2"

    def __init__(self, client: ModelClient, prompts: PromptRepository) -> None:
        self.client = client
        self.prompts = prompts

    def refine(
        self,
        facts: CaseFactStructure,
        candidate_issues: Sequence[LegalIssue],
        retrieval_trace: Sequence[RetrievalTrace],
    ) -> Tuple[List[RefinementAction], List[LegalIssue], Dict[str, Any]]:
        retrieval_ids = {trace.retrieval_id for trace in retrieval_trace}
        prompt = self.prompts.render(
            self.prompt_version,
            {
                "STRUCTURED_FACTS": json.dumps(facts.to_dict(), ensure_ascii=False, indent=2),
                "CANDIDATE_ISSUES": json.dumps(
                    [issue.to_dict() for issue in candidate_issues],
                    ensure_ascii=False,
                    indent=2,
                ),
                "RETRIEVAL_SUMMARY": render_retrieval_summary(retrieval_trace),
            },
        )
        value, provenance, _, _ = self.client.call_json(
            prompt,
            lambda payload: parse_refinement_payload(
                payload,
                facts,
                candidate_issues,
                retrieval_ids,
            ),
            prompt_version=self.prompt_version,
            stage="retrieval_refinement",
        )
        actions, final_issues = value
        return actions, final_issues, provenance
