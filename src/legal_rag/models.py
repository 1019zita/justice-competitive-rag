"""Data models for the frozen-case machine slice.

Two families live here on purpose:

* **Canonical (Gate 2/3) schema** — field names follow
  ``docs/02_design/DATA_SCHEMA.md`` and identifier syntax follows
  ``docs/02_design/CASE_RESEARCH_CONTRACT.md`` §1.  Everything the canonical
  retrieval pipeline touches is in this family.
* **Legacy prototype containers** — kept only because ``chunking.py``,
  ``knowledge.py`` and ``audit.py`` still import them.  The canonical pipeline
  never reads ``LegalDocument.stance`` / ``is_gold`` and never treats them as
  gold or ranking input.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Canonical schema constants (docs/02_design/CASE_RESEARCH_CONTRACT.md §1.1)
# ---------------------------------------------------------------------------

UNKNOWN = "unknown"
NOT_ASSESSED = "not_assessed"

MACHINE_STATUS_EXTRACTED = "extracted_from_frozen_input"
MACHINE_STATUS_CANDIDATE = "machine_candidate"
MACHINE_STATUS_UNKNOWN = "unknown"

HUMAN_STATUS_PENDING = "pending_human_confirmation"
HUMAN_STATUS_CONFIRMED = "human_confirmed"
HUMAN_STATUS_NA = "not_applicable"

# ``evidence_audit.human_confirmed`` (DATA_SCHEMA.md §6.9) is its own enum: it records
# whether a *human* confirmed one dimension row, not the machine/human status of a
# claim or document record.
HUMAN_CONFIRMED_TRUE = "true"
HUMAN_CONFIRMED_FALSE = "false"
HUMAN_CONFIRMED_NOT_REVIEWED = "not_reviewed"
HUMAN_CONFIRMED_VALUES = (
    HUMAN_CONFIRMED_TRUE,
    HUMAN_CONFIRMED_FALSE,
    HUMAN_CONFIRMED_NOT_REVIEWED,
)

#: Traceability fields required once a row is not ``not_reviewed`` (DATA_SCHEMA.md §6.9
#: 「人工追溯约束」).
EVIDENCE_REVIEW_FIELDS = ("review_id", "annotator_id", "review_note")

HYPOTHESIS_BINARY = "binary_legal_conclusion"
HYPOTHESIS_BAND = "team_hypothesis_band"
HYPOTHESIS_OPEN = "unresolved_interpretive_space"

ROUTE_NEUTRAL = "neutral_governing"
ROUTE_SUPPORT = "support"
ROUTE_COUNTER = "counter_weakening"
ROUTE_BASELINE = "baseline_single"

EVIDENCE_DIMENSIONS = (
    "existence",
    "validity",
    "jurisdiction_applicability",
    "quotation_fidelity",
    "claim_entailment",
)

#: D3 applicability is the only dimension allowed to use ``not_applicable``.
EVIDENCE_STATUS_VALUES: Dict[str, tuple] = {
    "existence": ("pass", "fail", "unknown", "not_assessed"),
    "validity": (
        "in_force",
        "amended",
        "repealed",
        "superseded",
        "not_yet_effective",
        "unknown",
        "not_assessed",
    ),
    "jurisdiction_applicability": (
        "applicable",
        "partially_applicable",
        "not_applicable",
        "not_enough_info",
        "not_assessed",
    ),
    "quotation_fidelity": (
        "exact_match",
        "normalized_match",
        "partial",
        "not_found",
        "not_assessed",
    ),
    "claim_entailment": ("supported", "refuted", "not_enough_info", "not_assessed"),
}


@dataclass
class Provenance:
    """Where a record came from and how it was extracted."""

    source_path: str
    source_sha256: str
    extraction_method: str
    extracted_at: str
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# L1 — source and document truth
# ---------------------------------------------------------------------------


@dataclass
class SourceRepository:
    """``SRC-DB-*``: a discovery host.  Host != legal authority."""

    source_scope_id: str
    order: int
    name_zh: str
    authority_role: str = "host_discovery"
    platform_class_machine_candidate: str = UNKNOWN
    jurisdiction_machine_candidate: str = UNKNOWN
    official_url: str = UNKNOWN
    discovery_url: str = UNKNOWN
    access_status: str = UNKNOWN
    access_claimed: bool = False
    machine_status: str = MACHINE_STATUS_EXTRACTED
    human_status: str = HUMAN_STATUS_PENDING
    provenance: Optional[Provenance] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SourceAuthorityScope:
    """``SRC-AUTH-*``: a legal-authority entry listed by the frozen workbook."""

    source_scope_id: str
    case_id: str
    order: int
    title: str
    publisher: str
    document_type_as_written: str
    authority_role: str = "source_authority"
    authority_tier: str = UNKNOWN
    validity_status: str = UNKNOWN
    official_url: str = UNKNOWN
    discovery_url: str = UNKNOWN
    access_status: str = UNKNOWN
    document_discovery: List[str] = field(default_factory=list)
    verification_flags: List[str] = field(default_factory=list)
    machine_status: str = MACHINE_STATUS_EXTRACTED
    human_status: str = HUMAN_STATUS_PENDING

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SourceDocument:
    """L1 document record.  Metadata-only here: no source bytes were fetched."""

    doc_id: str
    source_scope_id: str
    authority_role: str
    title: str
    document_type: str
    document_type_as_written: str
    document_type_status: str
    source_authority: str
    authority_tier: str = UNKNOWN
    validity_status: str = UNKNOWN
    jurisdiction: str = UNKNOWN
    jurisdiction_level: str = UNKNOWN
    official_url: str = UNKNOWN
    discovery_url: str = UNKNOWN
    access_status: str = UNKNOWN
    ingest_status: str = "metadata_only"
    not_retrieved_reason: str = ""
    first_seen_corpus_version: str = ""
    machine_status: str = MACHINE_STATUS_EXTRACTED
    human_status: str = HUMAN_STATUS_PENDING
    retrieved_at: Optional[str] = None
    bytes_sha256: Optional[str] = None
    # --- case-material bibliographic fields (optional; empty for statutes) ---
    case_number: str = ""
    court: str = ""
    judgment_date: Optional[str] = None
    publication_date: Optional[str] = None
    database_category: str = ""
    source_database: str = ""
    raw_file_relative_path: str = ""
    discovery_task_ids: str = ""
    discovery_query_groups: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentTextVersion:
    text_version_id: str
    doc_id: str
    version_no: int
    normalizer_version: str
    normalization_ops: List[str]
    normalized_text: str
    text_sha256: str
    char_length: int
    offset_basis: str = "unicode_code_point"
    is_current: bool = True
    extraction_loss_note: str = ""
    created_at: str = ""
    # --- historical-version provenance (optional; empty for ordinary versions) ---
    historical_version_label: str = ""
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    publication_date: Optional[str] = None
    source_url: str = ""
    source_provenance: str = ""
    raw_file_relative_path: str = ""
    raw_sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# L2 — frozen case / issue / hypothesis structure (human-frozen inputs)
# ---------------------------------------------------------------------------


@dataclass
class FactorRecord:
    factor_id: str
    issue_id: str
    case_id: str
    ordinal: int
    text: str
    factor_type: str
    statutory_basis: str = UNKNOWN
    machine_status: str = MACHINE_STATUS_EXTRACTED
    human_status: str = HUMAN_STATUS_PENDING

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IssueRecord:
    case_id: str
    issue_id: str
    ordinal: int
    issue_text: str
    factors: List[FactorRecord] = field(default_factory=list)
    machine_status: str = MACHINE_STATUS_EXTRACTED
    human_status: str = HUMAN_STATUS_PENDING

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["factors"] = [factor.to_dict() for factor in self.factors]
        return data


@dataclass
class HypothesisRecord:
    case_id: str
    hypothesis_id: str
    ordinal: int
    text: str
    hypothesis_status: str
    statutory_basis: str = UNKNOWN
    status_basis: str = "workbook"
    band_label: str = ""
    baseline_pct: Optional[int] = None
    team_hypothesis_note: str = ""
    machine_status: str = MACHINE_STATUS_EXTRACTED
    human_status: str = HUMAN_STATUS_PENDING

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OpenSpaceMarker:
    """``<case_id>-H?``: query-time open unknown.  Never a hypothesis, never gold."""

    case_id: str
    marker_id: str
    note: str
    instantiable: bool = False
    machine_status: str = MACHINE_STATUS_UNKNOWN
    human_status: str = HUMAN_STATUS_PENDING

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UnknownFact:
    case_id: str
    item: str
    detail: str = ""
    machine_status: str = MACHINE_STATUS_UNKNOWN
    human_status: str = HUMAN_STATUS_PENDING
    declared_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CaseRecord:
    case_id: str
    display_name: str
    short_name: str
    domain: str
    summary: str
    source_row_index: int
    integrity_note: str = ""
    machine_status: str = MACHINE_STATUS_EXTRACTED
    human_status: str = HUMAN_STATUS_PENDING

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FrozenCase:
    case: CaseRecord
    issues: List[IssueRecord]
    hypotheses: List[HypothesisRecord]
    open_marker: OpenSpaceMarker
    unknown_facts: List[UnknownFact]
    source_authority_scopes: List[SourceAuthorityScope]

    @property
    def case_id(self) -> str:
        return self.case.case_id

    def hypothesis(self, hypothesis_id: str) -> HypothesisRecord:
        for item in self.hypotheses:
            if item.hypothesis_id == hypothesis_id:
                return item
        raise KeyError(hypothesis_id)

    def triples(self) -> List[tuple]:
        """``(case_id, issue_id, hypothesis_id)`` in frozen order."""
        return [
            (self.case_id, issue.issue_id, hypothesis.hypothesis_id)
            for issue in self.issues
            for hypothesis in self.hypotheses
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case": self.case.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "open_marker": self.open_marker.to_dict(),
            "unknown_facts": [item.to_dict() for item in self.unknown_facts],
            "source_authority_scopes": [
                item.to_dict() for item in self.source_authority_scopes
            ],
        }


@dataclass
class FrozenCorpus:
    """Everything loaded from the two frozen inputs, plus provenance."""

    cases: List[FrozenCase]
    source_repositories: List[SourceRepository]
    corpus_version: str
    loader_version: str
    provenance: List[Provenance]
    loaded_at: str

    @property
    def case_ids(self) -> List[str]:
        return [item.case_id for item in self.cases]

    def case(self, case_id: str) -> FrozenCase:
        for item in self.cases:
            if item.case_id == case_id:
                return item
        raise KeyError(case_id)

    def source_authority_scopes(self) -> List[SourceAuthorityScope]:
        scopes: List[SourceAuthorityScope] = []
        for item in self.cases:
            scopes.extend(item.source_authority_scopes)
        return scopes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "corpus_version": self.corpus_version,
            "loader_version": self.loader_version,
            "loaded_at": self.loaded_at,
            "case_count": len(self.cases),
            "source_repository_count": len(self.source_repositories),
            "source_authority_scope_count": len(self.source_authority_scopes()),
            "provenance": [item.to_dict() for item in self.provenance],
            "cases": [item.to_dict() for item in self.cases],
            "source_repositories": [item.to_dict() for item in self.source_repositories],
        }


# ---------------------------------------------------------------------------
# L3 — generated retrieval artefacts
# ---------------------------------------------------------------------------


@dataclass
class VersionedChunk:
    chunk_id: str
    doc_id: str
    text_version_id: str
    source_scope_id: str
    ordinal: int
    heading: str
    chunk_type: str
    span_start: int
    span_end: int
    chunk_text: str
    chunk_sha256: str
    embedding_text: str
    embedding_text_sha256: str
    char_count: int
    overlap_prev_chars: int
    chunker_version: str
    corpus_version: str
    structure_confidence: str
    leakage_guard_ok: bool
    # --- CV-0005 wrapper-cleaning provenance (optional; empty for older corpora) ---
    export_wrapper_kind: str = "none"
    export_header_span: Optional[Tuple[int, int]] = None
    body_span: Optional[Tuple[int, int]] = None
    raw_text_version_id: str = ""
    raw_file_relative_path: str = ""
    raw_sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ApplicabilityFlags:
    validity: str = UNKNOWN
    jurisdiction: str = UNKNOWN
    doc_type: str = UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QueryTrace:
    query_id: str
    run_id: str
    case_id: str
    issue_id: str
    hypothesis_id: str
    route: str
    route_rationale: str
    query_text: str
    query_construction: str
    retrieval_channel: str
    top_k: int
    created_at: str
    parent_query_id: Optional[str] = None
    unknown_facts: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)
    leakage_guard_ok: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    result_id: str
    run_id: str
    query_id: str
    chunk_id: str
    doc_id: str
    source_scope_id: str
    text_version_id: str
    span_start: int
    span_end: int
    route: str
    rank_raw: int
    rank_final: int
    score_sparse: float
    score_dense: Optional[float]
    score_fusion: Optional[float]
    score_rerank: Optional[float]
    authority_multiplier: Optional[float]
    applicability_flags: ApplicabilityFlags
    selected: bool
    omission_reason: Optional[str]
    was_gold: str = NOT_ASSESSED

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["applicability_flags"] = self.applicability_flags.to_dict()
        return data


def _is_blank(value: Optional[str]) -> bool:
    """A field counts as absent when it is ``None`` or whitespace-only."""

    return value is None or not str(value).strip()


@dataclass
class EvidenceAuditRow:
    """One ``evidence_audit`` dimension row (DATA_SCHEMA.md §6.9).

    Five dimensions are stored as independent rows and are never fused into a score.
    ``human_confirmed`` is the per-row human-confirmation state; the traceability
    fields are enforced on construction, see :meth:`validate`.
    """

    dimension: str
    status: str
    method: str
    detail: Dict[str, Any]
    target_type: str = "retrieval_result"
    result_id: Optional[str] = None
    claim_id: Optional[str] = None
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    prompt_hash: Optional[str] = None
    audited_at: str = ""
    human_confirmed: str = HUMAN_CONFIRMED_NOT_REVIEWED
    review_id: Optional[str] = None
    annotator_id: Optional[str] = None
    review_note: Optional[str] = None

    def __post_init__(self) -> None:
        # Construction-path enforcement: an untraceable or falsely human-reviewed row
        # must not be representable at all (DATA_SCHEMA.md §6.9 「人工追溯约束」).
        self.validate()

    def validate(self) -> None:
        """Raise ``ValueError`` when the human-confirmation linkage is inconsistent.

        Rules (DATA_SCHEMA.md §6.9):

        * ``human_confirmed`` must be one of ``true`` / ``false`` / ``not_reviewed``;
        * a row that is not ``not_reviewed`` carries a human review outcome, so
          ``review_id`` (fk ``annotation_review.review_id``), ``annotator_id`` and
          ``review_note`` are all mandatory and non-blank — including ``false``, since a
          rejected confirmation is still a human review and must stay traceable;
        * a machine-produced row stays ``not_reviewed`` and must not carry any reviewer
          field, so it can never look human-reviewed.
        """

        if self.human_confirmed not in HUMAN_CONFIRMED_VALUES:
            raise ValueError(
                f"evidence_audit.human_confirmed {self.human_confirmed!r} is not one of "
                f"{list(HUMAN_CONFIRMED_VALUES)} (DATA_SCHEMA.md §6.9)"
            )

        supplied = [
            name for name in EVIDENCE_REVIEW_FIELDS if not _is_blank(getattr(self, name))
        ]

        if self.human_confirmed == HUMAN_CONFIRMED_NOT_REVIEWED:
            if supplied:
                raise ValueError(
                    "evidence_audit row with human_confirmed='not_reviewed' must not carry "
                    f"reviewer fields {supplied}; machine-produced rows stay 'not_reviewed' "
                    "and must not look human-reviewed (DATA_SCHEMA.md §6.9)"
                )
            return

        missing = [name for name in EVIDENCE_REVIEW_FIELDS if name not in supplied]
        if missing:
            raise ValueError(
                f"evidence_audit row with human_confirmed={self.human_confirmed!r} requires "
                f"non-blank {missing} (DATA_SCHEMA.md §6.9: human_confirmed=true 时 "
                "review_id / annotator_id / review_note 必填)"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BudgetVector:
    queries: int
    candidates_scored: int
    rerank_pairs: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CostModel:
    version: str
    weights: Dict[str, float]
    unit_note: str

    def total(self, budget: BudgetVector) -> float:
        return (
            budget.queries * self.weights["queries"]
            + budget.candidates_scored * self.weights["candidates_scored"]
            + budget.rerank_pairs * self.weights["rerank_pairs"]
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalRun:
    run_id: str
    pipeline: str
    case_id: str
    index_version: str
    corpus_version: str
    config: Dict[str, Any]
    config_hash: str
    query_set_version: str
    query_set_manifest_hash: str
    budget_vector: BudgetVector
    cost_model_version: str
    total_budget: float
    budget_limit_vector: BudgetVector
    budget_limit_total: float
    actual_usage_vector: BudgetVector
    actual_cost: float
    run_manifest_id: str
    run_manifest_hash: str
    started_at: str
    finished_at: str
    code_version: str
    operator: str
    status: str = "completed"
    failure_note: Optional[str] = None
    gold_set_version: Optional[str] = None
    gold_manifest_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["budget_vector"] = self.budget_vector.to_dict()
        data["budget_limit_vector"] = self.budget_limit_vector.to_dict()
        data["actual_usage_vector"] = self.actual_usage_vector.to_dict()
        return data


@dataclass
class BiasAuditSummary:
    run_id: str
    metrics: Dict[str, Any]
    undefined_metrics: Dict[str, str]
    route_coverage: Dict[str, Any]
    substantive_coverage: Dict[str, str]
    warnings: List[str]
    omitted_gold: Dict[str, str]
    computed_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunArtifact:
    """One JSON-serializable run: traces, results, audit.  No evaluation score."""

    run: RetrievalRun
    queries: List[QueryTrace]
    results: List[RetrievalResult]
    bias_audit: BiasAuditSummary
    evidence_audit: List[EvidenceAuditRow]
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "queries": [item.to_dict() for item in self.queries],
            "results": [item.to_dict() for item in self.results],
            "bias_audit": self.bias_audit.to_dict(),
            "evidence_audit": [item.to_dict() for item in self.evidence_audit],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Legacy prototype containers (see module docstring).  Not used by the
# canonical pipeline; retained because chunking/knowledge/audit still import
# them.  ``stance`` / ``stance_hypothesis`` / ``is_gold`` MUST NOT be used as
# ranking features or as gold by any canonical code path.
# ---------------------------------------------------------------------------


@dataclass
class LegalDocument:
    doc_id: str
    domain: str
    source: str
    document_type: str
    title: str
    valid: bool
    jurisdiction: str
    stance: str
    stance_hypothesis: str
    text: str
    url: str = ""
    authority: float = 0.5
    effective_date: Optional[str] = None
    is_gold: Optional[bool] = None
    issue_tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Hypothesis:
    hypothesis_id: str
    label: str
    description: str
    status: str = "candidate"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievedEvidence:
    doc_id: str
    title: str
    text: str
    query_type: str
    hypothesis_id: str
    raw_score: float
    final_score: float
    authority: float
    stance: str
    bridge_hit: bool
    matched_cues: List[str] = field(default_factory=list)
    chunk_id: str = ""
    source: str = ""
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    hypothesis_coverage: Dict[str, float]
    counter_evidence_recall: Dict[str, Optional[float]]
    exposure_entropy: float
    exposure_hhi: float
    exposure_imbalance: float
    edge_case_hits: List[str]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CaseAnalysis:
    case_id: str
    facts: str
    domain: str
    issues: List[str]
    known_facts: List[str]
    unknown_facts: List[str]
    hypotheses: List[Hypothesis]
    evidence: Dict[str, List[RetrievedEvidence]]
    audit: AuditReport
    provisional_opinion: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "facts": self.facts,
            "domain": self.domain,
            "issues": self.issues,
            "known_facts": self.known_facts,
            "unknown_facts": self.unknown_facts,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "evidence": {
                key: [item.to_dict() for item in value]
                for key, value in self.evidence.items()
            },
            "audit": self.audit.to_dict(),
            "provisional_opinion": self.provisional_opinion,
        }
