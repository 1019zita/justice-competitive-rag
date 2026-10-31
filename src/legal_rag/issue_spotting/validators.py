"""Deterministic validators for fact and issue contracts."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .models import (
    CaseFactStructure,
    FactSpan,
    IssueProvenance,
    LegalIssue,
    PROVENANCE_STAGES,
    REFINEMENT_ACTIONS,
    ISSUE_TYPES,
    IMPORTANCE_LEVELS,
    CONFIDENCE_LEVELS,
    RefinementAction,
)

FACT_FIELDS = CaseFactStructure.field_names()
FACT_ID_RE = re.compile(r"^[FM]-\d{3,}$")
ISSUE_ID_RE = re.compile(r"^ISS-\d{3,}$")
INTERNAL_ID_RE = re.compile(r"(?:CASE-\d{2}|CASE\d{2}|H[1-6]|H\?)")
CONCLUSION_RE = re.compile(
    r"(?:因此|所以|必然|已经违法|已经合法|构成犯罪|成立正当防卫|应当返还\s*\d|胜诉|败诉|应判|必然承担)"
)


class ContractError(ValueError):
    def __init__(self, message: str, errors: Optional[Sequence[str]] = None) -> None:
        self.errors = list(errors or [message])
        super().__init__(message)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return value


def _string(value: Any, label: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be a string")
    if not allow_empty and not value.strip():
        raise ContractError(f"{label} must not be empty")
    return value.strip() if not allow_empty else value


def _string_list(value: Any, label: str, max_items: Optional[int] = None) -> List[str]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be a list")
    if max_items is not None and len(value) > max_items:
        raise ContractError(f"{label} has more than {max_items} items")
    result: List[str] = []
    for index, item in enumerate(value):
        result.append(_string(item, f"{label}[{index}]"))
    if len(result) != len(set(result)):
        raise ContractError(f"{label} contains duplicates")
    return result


def _span(value: Any, label: str) -> Optional[Tuple[int, int]]:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, int) for v in value):
        raise ContractError(f"{label} must be null or [integer, integer]")
    start, end = value
    if start < 0 or end < start:
        raise ContractError(f"{label} must satisfy 0 <= start <= end")
    return start, end


def _span_matches(raw: str, text: str, source_span: Tuple[int, int]) -> bool:
    start, end = source_span
    if end > len(raw):
        return False
    return raw[start:end].strip() == text.strip()


def _unique_exact_span(raw: str, text: str) -> Optional[Tuple[int, int]]:
    needle = text.strip()
    if not needle:
        return None
    starts: List[int] = []
    cursor = raw.find(needle)
    while cursor >= 0:
        starts.append(cursor)
        cursor = raw.find(needle, cursor + 1)
    if len(starts) == 1:
        start = starts[0]
        return start, start + len(needle)
    return None


def _parse_fact_item(payload: Any, label: str, raw: str, expected_status: str) -> FactSpan:
    item = _mapping(payload, label)
    allowed = {"fact_id", "text", "source_span", "fact_type", "status", "notes"}
    unknown = sorted(set(item) - allowed)
    if unknown:
        raise ContractError(f"{label} has unknown fields: {unknown}")
    fact_id = _string(item.get("fact_id"), f"{label}.fact_id")
    if not FACT_ID_RE.fullmatch(fact_id):
        raise ContractError(f"{label}.fact_id must match F-001 or M-001")
    text = _string(item.get("text"), f"{label}.text")
    fact_type = _string(item.get("fact_type"), f"{label}.fact_type")
    status = _string(item.get("status"), f"{label}.status")
    notes = item.get("notes", "")
    if not isinstance(notes, str):
        raise ContractError(f"{label}.notes must be a string")
    source_span = _span(item.get("source_span"), f"{label}.source_span")
    if expected_status == "unknown":
        if status != "unknown":
            raise ContractError(f"{label}.status must be unknown for missing_facts")
        if source_span is not None:
            raise ContractError(f"{label}.source_span must be null for missing_facts")
        if not fact_id.startswith("M-"):
            raise ContractError(f"{label}.fact_id must start with M- for missing_facts")
    else:
        if status != "explicit":
            raise ContractError(f"{label}.status must be explicit")
        if source_span is None:
            raise ContractError(f"{label}.source_span is required for explicit facts")
        if not _span_matches(raw, text, source_span):
            repaired_span = _unique_exact_span(raw, text)
            if repaired_span is None:
                raise ContractError(f"{label}.source_span does not slice back to text")
            source_span = repaired_span
            notes = (notes + "; " if notes else "") + "deterministic_span_realign"
        if not fact_id.startswith("F-"):
            raise ContractError(f"{label}.fact_id must start with F- for explicit facts")
    return FactSpan(
        fact_id=fact_id,
        text=text,
        source_span=source_span,
        fact_type=fact_type,
        status=status,
        notes=notes,
    )


def parse_fact_structure(payload: Any, raw_facts: str) -> CaseFactStructure:
    root = _mapping(payload, "fact structure")
    unknown = sorted(set(root) - set(FACT_FIELDS))
    if unknown:
        raise ContractError(f"fact structure has unknown fields: {unknown}")
    values: Dict[str, List[FactSpan]] = {}
    seen: Set[str] = set()
    for field_name in FACT_FIELDS:
        raw_items = root.get(field_name, [])
        if not isinstance(raw_items, list):
            raise ContractError(f"{field_name} must be a list")
        expected_status = "unknown" if field_name == "missing_facts" else "explicit"
        parsed: List[FactSpan] = []
        for index, item in enumerate(raw_items):
            fact = _parse_fact_item(item, f"{field_name}[{index}]", raw_facts, expected_status)
            if fact.fact_id in seen:
                raise ContractError(f"duplicate fact_id across structure: {fact.fact_id}")
            seen.add(fact.fact_id)
            parsed.append(fact)
        values[field_name] = parsed
    return CaseFactStructure(**values)


def _reject_internal_ids(value: Any, label: str) -> None:
    if isinstance(value, str) and INTERNAL_ID_RE.search(value):
        raise ContractError(f"{label} contains frozen case/hypothesis identifier")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_internal_ids(nested, f"{label}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_internal_ids(nested, f"{label}[{index}]")


def _parse_issue(
    payload: Any,
    label: str,
    facts: CaseFactStructure,
    expected_stage: str,
    known_retrieval_ids: Optional[Set[str]] = None,
) -> LegalIssue:
    item = _mapping(payload, label)
    allowed = {
        "issue_id",
        "question",
        "trigger_fact_ids",
        "legal_concepts",
        "inferred_legal_concepts",
        "issue_type",
        "importance",
        "confidence",
        "uncertainty_reason",
        "query_seeds",
        "provenance",
    }
    unknown = sorted(set(item) - allowed)
    if unknown:
        raise ContractError(f"{label} has unknown fields: {unknown}")
    issue_id = _string(item.get("issue_id"), f"{label}.issue_id")
    if not ISSUE_ID_RE.fullmatch(issue_id):
        raise ContractError(f"{label}.issue_id must match ISS-001")
    question = _string(item.get("question"), f"{label}.question")
    if "?" not in question and "？" not in question:
        raise ContractError(f"{label}.question must be phrased as a question")
    if CONCLUSION_RE.search(question):
        raise ContractError(f"{label}.question contains a conclusion-like phrase")
    trigger_ids = _string_list(item.get("trigger_fact_ids"), f"{label}.trigger_fact_ids")
    if not trigger_ids:
        raise ContractError(f"{label}.trigger_fact_ids must not be empty")
    explicit_ids = set(facts.explicit_by_id())
    unknown_triggers = sorted(set(trigger_ids) - explicit_ids)
    if unknown_triggers:
        raise ContractError(f"{label} has non-explicit or unknown trigger facts: {unknown_triggers}")
    legal_concepts = _string_list(item.get("legal_concepts"), f"{label}.legal_concepts", max_items=12)
    inferred = _string_list(
        item.get("inferred_legal_concepts", []),
        f"{label}.inferred_legal_concepts",
        max_items=12,
    )
    raw_issue_type = _string(item.get("issue_type"), f"{label}.issue_type")
    issue_type = {
        "remedial": "remedy",
        "legal": "substantive",
        "administrative": "procedural",
    }.get(raw_issue_type, raw_issue_type)
    if issue_type not in ISSUE_TYPES:
        raise ContractError(f"{label}.issue_type invalid: {raw_issue_type}")
    importance = _string(item.get("importance"), f"{label}.importance")
    if importance not in IMPORTANCE_LEVELS:
        raise ContractError(f"{label}.importance invalid: {importance}")
    confidence = _string(item.get("confidence"), f"{label}.confidence")
    if confidence not in CONFIDENCE_LEVELS:
        raise ContractError(f"{label}.confidence invalid: {confidence}")
    uncertainty_reason = item.get("uncertainty_reason")
    if uncertainty_reason is not None and not isinstance(uncertainty_reason, str):
        raise ContractError(f"{label}.uncertainty_reason must be string or null")
    query_seeds = _string_list(item.get("query_seeds"), f"{label}.query_seeds", max_items=8)
    if not query_seeds:
        raise ContractError(f"{label}.query_seeds must not be empty")
    for field_name, values in (
        ("legal_concepts", legal_concepts),
        ("inferred_legal_concepts", inferred),
        ("query_seeds", query_seeds),
    ):
        if any(CONCLUSION_RE.search(value) for value in values):
            raise ContractError(f"{label}.{field_name} contains a conclusion-like phrase")
    provenance = _mapping(item.get("provenance"), f"{label}.provenance")
    prov_stage = _string(provenance.get("stage"), f"{label}.provenance.stage")
    if prov_stage != expected_stage or prov_stage not in PROVENANCE_STAGES:
        raise ContractError(f"{label}.provenance.stage must be {expected_stage}")
    retrieval_ids = _string_list(
        provenance.get("supporting_retrieval_ids", []),
        f"{label}.provenance.supporting_retrieval_ids",
    )
    if known_retrieval_ids is not None:
        unknown_retrievals = sorted(set(retrieval_ids) - known_retrieval_ids)
        if unknown_retrievals:
            raise ContractError(f"{label} references unknown retrieval ids: {unknown_retrievals}")
    return LegalIssue(
        issue_id=issue_id,
        question=question,
        trigger_fact_ids=trigger_ids,
        legal_concepts=legal_concepts,
        inferred_legal_concepts=inferred,
        issue_type=issue_type,
        importance=importance,
        confidence=confidence,
        uncertainty_reason=uncertainty_reason,
        query_seeds=query_seeds,
        provenance=IssueProvenance(
            stage=prov_stage,
            supporting_retrieval_ids=retrieval_ids,
        ),
    )


def parse_issue_payload(
    payload: Any,
    facts: CaseFactStructure,
    expected_stage: str = "initial",
    known_retrieval_ids: Optional[Set[str]] = None,
) -> List[LegalIssue]:
    root = _mapping(payload, "issue payload")
    if set(root) != {"issues"}:
        unknown = sorted(set(root) - {"issues"})
        missing = [] if "issues" in root else ["issues"]
        raise ContractError(f"issue payload fields mismatch; missing={missing}, unknown={unknown}")
    raw_issues = root["issues"]
    if not isinstance(raw_issues, list):
        raise ContractError("issues must be a list")
    issues: List[LegalIssue] = []
    seen: Set[str] = set()
    for index, item in enumerate(raw_issues):
        issue = _parse_issue(item, f"issues[{index}]", facts, expected_stage, known_retrieval_ids)
        if issue.issue_id in seen:
            raise ContractError(f"duplicate issue_id: {issue.issue_id}")
        seen.add(issue.issue_id)
        issues.append(issue)
    _reject_internal_ids(payload, "issue payload")
    return issues


def parse_refinement_payload(
    payload: Any,
    facts: CaseFactStructure,
    candidate_issues: Sequence[LegalIssue],
    retrieval_ids: Set[str],
) -> Tuple[List[RefinementAction], List[LegalIssue]]:
    root = _mapping(payload, "refinement payload")
    if set(root) != {"actions", "final_issues"}:
        unknown = sorted(set(root) - {"actions", "final_issues"})
        missing = sorted({"actions", "final_issues"} - set(root))
        raise ContractError(f"refinement payload fields mismatch; missing={missing}, unknown={unknown}")
    candidate_ids = {issue.issue_id for issue in candidate_issues}
    raw_actions = root["actions"]
    if not isinstance(raw_actions, list):
        raise ContractError("actions must be a list")
    actions: List[RefinementAction] = []
    for index, raw_action in enumerate(raw_actions):
        item = _mapping(raw_action, f"actions[{index}]")
        allowed = {
            "action",
            "issue_id",
            "source_issue_ids",
            "question",
            "reason",
            "supporting_retrieval_ids",
        }
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise ContractError(f"actions[{index}] has unknown fields: {unknown}")
        action = _string(item.get("action"), f"actions[{index}].action")
        if action not in REFINEMENT_ACTIONS:
            raise ContractError(f"actions[{index}].action invalid: {action}")
        issue_id = item.get("issue_id")
        if issue_id is not None:
            issue_id = _string(issue_id, f"actions[{index}].issue_id")
            if issue_id not in candidate_ids and action not in {"ADD", "SPLIT"}:
                raise ContractError(f"actions[{index}] references unknown issue_id: {issue_id}")
        source_ids = _string_list(item.get("source_issue_ids", []), f"actions[{index}].source_issue_ids")
        if not set(source_ids).issubset(candidate_ids):
            raise ContractError(f"actions[{index}] references unknown source issue")
        question = item.get("question")
        if question is not None and not isinstance(question, str):
            raise ContractError(f"actions[{index}].question must be string or null")
        reason = _string(item.get("reason"), f"actions[{index}].reason")
        action_retrieval_ids = _string_list(
            item.get("supporting_retrieval_ids", []),
            f"actions[{index}].supporting_retrieval_ids",
        )
        if not set(action_retrieval_ids).issubset(retrieval_ids):
            raise ContractError(f"actions[{index}] references unknown retrieval id")
        actions.append(
            RefinementAction(
                action=action,
                issue_id=issue_id,
                source_issue_ids=source_ids,
                question=question,
                reason=reason,
                supporting_retrieval_ids=action_retrieval_ids,
            )
        )
    final_payload = {"issues": root["final_issues"]}
    final_issues = parse_issue_payload(
        final_payload,
        facts,
        expected_stage="retrieval_refined",
        known_retrieval_ids=retrieval_ids,
    )
    if not final_issues:
        raise ContractError("final_issues must not be empty")
    final_ids = {issue.issue_id for issue in final_issues}
    if any(action.action == "ADD" and not action.source_issue_ids for action in actions):
        added_ids = final_ids - candidate_ids
        if not added_ids:
            raise ContractError("ADD action must result in a new final issue")
    _reject_internal_ids(payload, "refinement payload")
    return actions, final_issues
