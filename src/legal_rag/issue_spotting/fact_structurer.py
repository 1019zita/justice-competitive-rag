"""Fact-only extraction stage for Baselines B and C."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .llm import ModelClient
from .models import CaseFactStructure, DynamicCaseInput, FactSpan
from .prompts import PromptRepository
from .validators import ContractError, parse_fact_structure


class FactStructurer:
    prompt_version = "FACT_STRUCTURE_V2"
    def __init__(self, client: ModelClient, prompts: PromptRepository) -> None:
        self.client = client
        self.prompts = prompts

    def structure(self, case_facts: DynamicCaseInput) -> Tuple[CaseFactStructure, Dict[str, Any]]:
        prompt = self.prompts.render(
            self.prompt_version,
            {"RAW_FACTS": case_facts.facts_text},
        )
        try:
            value, provenance, _, _ = self.client.call_json(
                prompt,
                lambda payload: parse_fact_structure(payload, case_facts.facts_text),
                prompt_version=self.prompt_version,
                stage="fact_structure",
            )
            return value, provenance
        except ContractError as exc:
            fallback = _deterministic_explicit_facts(case_facts.facts_text)
            return fallback, {
                "stage": "fact_structure",
                "prompt_version": self.prompt_version,
                "fallback": "deterministic_raw_span_fallback",
                "fallback_reason": str(exc),
                "fact_count": len(fallback.explicit_facts),
            }


def _deterministic_explicit_facts(raw_facts: str) -> CaseFactStructure:
    """Fail-safe grounding inventory when the structured JSON call is unavailable.

    This does not infer parties, legal concepts, or missing facts.  It only exposes
    exact contiguous spans so the downstream issue stage can remain grounded.
    """
    spans: List[FactSpan] = []
    for index, match in enumerate(
        re.finditer(r"[^。！？!?；;\n]+(?:[。！？!?；;]|$)", raw_facts),
        start=1,
    ):
        text = match.group(0).strip()
        if not text:
            continue
        start = match.start() + (len(match.group(0)) - len(match.group(0).lstrip()))
        end = start + len(text)
        spans.append(
            FactSpan(
                fact_id=f"F-{index:03d}",
                text=text,
                source_span=(start, end),
                fact_type="explicit_fact",
                status="explicit",
                notes="deterministic_raw_span_fallback",
            )
        )
    if not spans and raw_facts.strip():
        start = len(raw_facts) - len(raw_facts.lstrip())
        text = raw_facts.strip()
        spans.append(
            FactSpan(
                fact_id="F-001",
                text=text,
                source_span=(start, start + len(text)),
                fact_type="explicit_fact",
                status="explicit",
                notes="deterministic_raw_span_fallback",
            )
        )
    return CaseFactStructure(explicit_facts=spans)
