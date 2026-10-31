"""Single-pass and structured issue spotting stages."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from .llm import ModelClient
from .models import CaseFactStructure, DynamicCaseInput, LegalIssue
from .prompts import PromptRepository
from .validators import parse_issue_payload


class IssueSpotter:
    def __init__(self, client: ModelClient, prompts: PromptRepository) -> None:
        self.client = client
        self.prompts = prompts

    def single_pass(self, case_facts: DynamicCaseInput) -> Tuple[List[LegalIssue], Dict[str, Any]]:
        version = "ISSUE_SINGLEPASS_V2"
        prompt = self.prompts.render(version, {"RAW_FACTS": case_facts.facts_text})
        value, provenance, _, _ = self.client.call_json(
            prompt,
            lambda payload: parse_issue_payload(payload, _single_pass_fact_view(case_facts.facts_text)),
            prompt_version=version,
            stage="single_pass_issue_spotting",
        )
        return value, provenance

    def from_structured_facts(
        self,
        facts: CaseFactStructure,
        *,
        candidate: bool = False,
    ) -> Tuple[List[LegalIssue], Dict[str, Any]]:
        version = (
            "ISSUE_CANDIDATE_FROM_FACTS_V2"
            if candidate
            else "ISSUE_FROM_FACTS_V2"
        )
        stage = "candidate_issue_spotting" if candidate else "structured_issue_spotting"
        prompt = self.prompts.render(
            version,
            {"STRUCTURED_FACTS": json.dumps(facts.to_dict(), ensure_ascii=False, indent=2)},
        )
        value, provenance, _, _ = self.client.call_json(
            prompt,
            lambda payload: parse_issue_payload(payload, facts),
            prompt_version=version,
            stage=stage,
        )
        return value, provenance


def _single_pass_fact_view(raw_facts: str) -> CaseFactStructure:
    """Create validator-only explicit spans for raw text without exposing structure to the model.

    Baseline A's prompt is raw-facts-only.  The validator still requires grounding,
    so a deterministic sentence-level span inventory is built after the call.  It
    is not supplied to the model and is not a model-derived fact structure.
    """
    import re

    spans = []
    for index, match in enumerate(re.finditer(r"[^。！？!?；;\n]+(?:[。！？!?；;]|$)", raw_facts), start=1):
        text = match.group(0).strip()
        if not text:
            continue
        start = match.start() + (len(match.group(0)) - len(match.group(0).lstrip()))
        end = start + len(text)
        from .models import FactSpan

        spans.append(
            FactSpan(
                fact_id=f"F-{index:03d}",
                text=text,
                source_span=(start, end),
                fact_type="raw_sentence",
                status="explicit",
            )
        )
    if not spans and raw_facts.strip():
        from .models import FactSpan

        text = raw_facts.strip()
        start = raw_facts.find(text)
        spans = [
            FactSpan(
                fact_id="F-001",
                text=text,
                source_span=(start, start + len(text)),
                fact_type="raw_text",
                status="explicit",
            )
        ]
    return CaseFactStructure(explicit_facts=spans)
