"""Unified reusable Dynamic Legal Issue Spotting service."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from ..data import REPO_ROOT, sha256_file
from .broad_retrieval import BroadSparseRetriever
from .fact_structurer import FactStructurer
from .issue_refiner import IssueRefiner
from .issue_spotter import IssueSpotter
from .llm import ModelClient, sha256_text
from .models import (
    DynamicCaseInput,
    IssueSpottingConfig,
    IssueSpottingResult,
)
from .prompts import PromptRepository


CaseFactsLike = Union[str, DynamicCaseInput]


def spot_issues(
    case_facts: CaseFactsLike,
    *,
    config: Optional[Union[IssueSpottingConfig, Mapping[str, Any]]] = None,
    client: Optional[ModelClient] = None,
) -> IssueSpottingResult:
    """Run Baseline A, B, or C over arbitrary raw case facts.

    ``case_facts`` is the only case-specific input.  The service never loads the
    frozen workbook, frozen issues, or frozen hypotheses.  Baseline C loads only
    the explicitly configured corpus for broad experimental retrieval.
    """
    if isinstance(case_facts, str):
        case_input = DynamicCaseInput(case_facts)
    elif isinstance(case_facts, DynamicCaseInput):
        case_input = case_facts
    else:
        raise TypeError("case_facts must be a raw string or DynamicCaseInput")

    if isinstance(config, IssueSpottingConfig):
        runtime = config
    else:
        runtime = IssueSpottingConfig.from_mapping(config)
    method = runtime.method.upper()
    if method not in {"A", "B", "C"}:
        raise ValueError("issue spotting method must be A, B, or C")

    prompts = PromptRepository(runtime.prompt_dir)
    corpus_dir = Path(runtime.corpus_dir)
    if not corpus_dir.is_absolute():
        corpus_dir = REPO_ROOT / corpus_dir
    corpus_manifest_path = corpus_dir / "manifest.json"
    corpus_manifest_hash = (
        sha256_file(corpus_manifest_path) if corpus_manifest_path.is_file() else None
    )
    model_client = client or ModelClient(runtime, prompts=prompts)
    spotter = IssueSpotter(model_client, prompts)
    warnings = []
    stage_provenance: Dict[str, Any] = {}
    structured_facts = None
    retrieval_trace = []
    refinement_actions = []

    if method == "A":
        issues, call_provenance = spotter.single_pass(case_input)
        stage_provenance["single_pass_issue_spotting"] = call_provenance
        candidate_issues = list(issues)
        final_issues = list(issues)
        warnings.append("Baseline A intentionally omits a separate fact-structuring stage")
    else:
        structurer = FactStructurer(model_client, prompts)
        structured_facts, fact_provenance = structurer.structure(case_input)
        stage_provenance["fact_structure"] = fact_provenance
        if fact_provenance.get("fallback"):
            warnings.append(
                "Fact structure provider contract failed; deterministic exact-span fallback was used"
            )
        if method == "B":
            issues, call_provenance = spotter.from_structured_facts(structured_facts)
            stage_provenance["structured_issue_spotting"] = call_provenance
            candidate_issues = list(issues)
            final_issues = list(issues)
        else:
            candidate_issues, candidate_provenance = spotter.from_structured_facts(
                structured_facts,
                candidate=True,
            )
            stage_provenance["candidate_issue_spotting"] = candidate_provenance
            retriever = BroadSparseRetriever(
                runtime.corpus_dir,
                scope_mode=runtime.scope_mode,
                top_k=runtime.top_k,
                exclude_doc_ids=runtime.exclude_doc_ids,
            )
            retrieval_trace = retriever.retrieve_for_issues(candidate_issues)
            refinement = IssueRefiner(model_client, prompts)
            refinement_actions, final_issues, refinement_provenance = refinement.refine(
                structured_facts,
                candidate_issues,
                retrieval_trace,
            )
            stage_provenance["retrieval_refinement"] = refinement_provenance

    provenance = {
        "module": "legal_rag.issue_spotting",
        "method": method,
        "input_hash": sha256_text(case_input.facts_text),
        "corpus_manifest_hash": corpus_manifest_hash,
        "config": runtime.to_dict(),
        "stages": stage_provenance,
        "input_contract": {
            "raw_case_input": True,
            "frozen_issue_input": False,
            "frozen_hypothesis_input": False,
            "case_id_required": False,
        },
        "retrieval_contract": {
            "used": bool(retrieval_trace),
            "experimental_scope_name": "experimental_shared_scope",
            "scope_mode": runtime.scope_mode if method == "C" else None,
            "exclude_doc_ids": list(runtime.exclude_doc_ids),
            "indexed_doc_ids": (
                retrieval_trace[0].indexed_doc_ids if retrieval_trace else []
            ),
            "retrieval_is_coverage_check_only": True,
        },
    }
    return IssueSpottingResult(
        case_facts=case_input,
        structured_facts=structured_facts,
        candidate_issues=candidate_issues,
        retrieval_trace=retrieval_trace,
        final_issues=final_issues,
        warnings=warnings,
        provenance=provenance,
        refinement_actions=refinement_actions,
    )
