"""Atomic claims and their evidence edges (``DATA_SCHEMA.md`` §6.8/§6.9).

What this module enforces
-------------------------
* **Evidence closure.**  A claim's evidence edge is ``cited_result_id`` +
  ``cited_doc_id`` + ``cited_span`` (``DATA_SCHEMA.md`` §6.8).  ``linked`` requires
  all three, and requires the doc id to equal the cited result's ``doc_id`` and the
  span to fall inside the cited result's ``text_version_id``
  (``EVIDENCE_AUDIT_DESIGN.md`` §8).  Anything else resolves to ``unlinked``; a
  claim with no edge at all resolves to ``not_assessed``.
* **D5 gating.**  ``claim_entailment`` (D5) is emitted *only* for a claim whose edge
  resolved to ``linked``.  For such a claim the row is ``not_assessed`` unless a real
  judgement was supplied — the code never invents ``supported``/``refuted``
  (``EVIDENCE_AUDIT_DESIGN.md`` §1.3, §4.2).  A claim without a valid edge gets no D5
  row at all, and a caller that hands in a judgement for an unlinked claim is refused
  instead of silently downgraded.
* **Target discipline.**  §6.9 「目标互斥约束」 (exactly one of ``result_id`` /
  ``claim_id`` set, consistent with ``target_type``) and 「维度目标约束」 (``claim``
  targets carry only ``claim_entailment``; the other four dimensions target a
  ``retrieval_result``) are checked by :func:`validate_evidence_audit_row`.

Honest limits
-------------
* No NLI/LLM backend is bundled.  D5 therefore stays ``not_assessed`` unless a
  caller supplies an :class:`EntailmentJudgement`; a machine ``supported`` is only
  accepted with human confirmation (``EVIDENCE_AUDIT_DESIGN.md`` §4.2.1, §7.4).
* Nothing here produces gold, a relation label, or a fused confidence score.  Five
  dimensions stay independent rows.
* Span checks follow §6.8 literally: the cited span must lie inside the cited
  result's *text version*.  Containment inside the result's own span is *not*
  additionally required, because the design does not require it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .models import (
    EVIDENCE_DIMENSIONS,
    EVIDENCE_STATUS_VALUES,
    HUMAN_CONFIRMED_NOT_REVIEWED,
    HUMAN_CONFIRMED_TRUE,
    HUMAN_STATUS_CONFIRMED,
    HUMAN_STATUS_NA,
    HUMAN_STATUS_PENDING,
    MACHINE_STATUS_CANDIDATE,
    MACHINE_STATUS_EXTRACTED,
    MACHINE_STATUS_UNKNOWN,
    NOT_ASSESSED,
    EvidenceAuditRow,
)

#: ``claim_record.claim_type`` (``DATA_SCHEMA.md`` §6.8).
CLAIM_TYPES = ("rule_statement", "fact_assertion", "application", "conclusion")

#: ``claim_record.decomposition_method`` (``DATA_SCHEMA.md`` §6.8).
DECOMPOSITION_METHODS = ("rule_split", "llm_split", "manual")

EVIDENCE_EDGE_LINKED = "linked"
EVIDENCE_EDGE_UNLINKED = "unlinked"
EVIDENCE_EDGE_NOT_ASSESSED = NOT_ASSESSED

#: ``claim_record.evidence_edge_status`` (``DATA_SCHEMA.md`` §6.8).
EVIDENCE_EDGE_STATUSES = (
    EVIDENCE_EDGE_LINKED,
    EVIDENCE_EDGE_UNLINKED,
    EVIDENCE_EDGE_NOT_ASSESSED,
)

#: ``evidence_audit.target_type`` (``DATA_SCHEMA.md`` §6.9).
EVIDENCE_TARGET_TYPES = ("retrieval_result", "claim")

#: ``target_type=claim`` is allowed for exactly one dimension (§6.9 「维度目标约束」).
CLAIM_SCOPED_DIMENSION = "claim_entailment"
RESULT_SCOPED_DIMENSIONS = tuple(
    dimension for dimension in EVIDENCE_DIMENSIONS if dimension != CLAIM_SCOPED_DIMENSION
)

#: D5 status values (``DATA_SCHEMA.md`` §6.9; ``EVIDENCE_AUDIT_DESIGN.md`` §5.2).
D5_STATUSES = tuple(EVIDENCE_STATUS_VALUES[CLAIM_SCOPED_DIMENSION])
D5_EVALUATED_STATUSES = ("supported", "refuted", "not_enough_info")

#: ``evidence_audit.method`` values a D5 row may carry (§6.9 method enum).
D5_METHODS = ("nli_model", "llm_assist", "human_review", "manual_review")

#: ``<case_id>-H<n>``.  ``H?`` / ``HX`` are query-time markers and never hypotheses
#: (``CASE_RESEARCH_CONTRACT.md`` §1.1, ``DATA_SCHEMA.md`` §6.8).
HYPOTHESIS_ID_PATTERN = re.compile(r"^CASE-\d{2}-H[1-9]\d*$")

_EDGE_FIELDS = ("cited_result_id", "cited_doc_id", "cited_span")


def _is_blank(value: Any) -> bool:
    """A value counts as absent when it is ``None`` or whitespace-only."""

    return value is None or (isinstance(value, str) and not value.strip())


def source_text_sha256(text: str) -> str:
    """``claim_record.source_text_hash`` for a frozen generated text (§6.8)."""

    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CitedSpan:
    """``cited_span`` = ``{text_version_id, span_start, span_end}`` (§6.8).

    Offsets are Unicode code-point half-open intervals ``[start, end)`` into the
    ``text_version_id`` text — never raw byte offsets (§1.3, §4.3).
    """

    text_version_id: str
    span_start: int
    span_end: int

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if _is_blank(self.text_version_id):
            raise ValueError("cited_span.text_version_id must be non-blank (DATA_SCHEMA.md §6.8)")
        for name in ("span_start", "span_end"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    f"cited_span.{name} must be an int code-point offset, got {value!r} "
                    "(DATA_SCHEMA.md §4.3)"
                )
        if self.span_start < 0:
            raise ValueError(f"cited_span.span_start must be >= 0, got {self.span_start}")
        if self.span_end <= self.span_start:
            raise ValueError(
                f"cited_span must be a non-empty half-open interval [start, end), got "
                f"[{self.span_start}, {self.span_end})"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TextVersionExtent:
    """``text_version_id -> (doc_id, char_length)`` view used to bound a cited span.

    This is not an L1 record: it is a read-only projection of a real
    ``document_text_version`` row (or of the index chunks built from it), and it
    exists so the span check never needs the full text.  The resolver accepts any
    object exposing ``doc_id`` and ``char_length``, including
    :class:`legal_rag.models.DocumentTextVersion` itself.
    """

    text_version_id: str
    doc_id: str
    char_length: int

    @classmethod
    def from_text_versions(cls, versions: Iterable[Any]) -> Dict[str, "TextVersionExtent"]:
        return {
            version.text_version_id: cls(
                text_version_id=version.text_version_id,
                doc_id=version.doc_id,
                char_length=int(version.char_length),
            )
            for version in versions
        }

    @classmethod
    def from_chunks(cls, chunks: Iterable[Any]) -> Dict[str, "TextVersionExtent"]:
        """Extents derived from index chunks.

        A chunk's ``[span_start, span_end)`` is a slice of its text version, so
        ``span_end`` is always a valid upper bound for offsets of that version (the
        longest end wins when a version was split into several chunks).  When a text
        version is only partially chunked the bound is conservative: a span past the
        chunked part is rejected rather than wrongly accepted.
        """

        extents: Dict[str, TextVersionExtent] = {}
        for chunk in chunks:
            version_id = chunk.text_version_id
            length = int(chunk.span_end)
            current = extents.get(version_id)
            if current is None or length > current.char_length:
                extents[version_id] = cls(
                    text_version_id=version_id, doc_id=chunk.doc_id, char_length=length
                )
        return extents


@dataclass
class ClaimRecord:
    """One atomic claim (``DATA_SCHEMA.md`` §6.8).

    ``evidence_edge_status`` defaults to ``not_assessed``: a freshly decomposed claim
    has no evidence edge until :func:`resolve_evidence_edge` says otherwise.
    """

    claim_id: str
    run_id: str
    source_text_hash: str
    claim_text: str
    claim_type: str
    decomposition_method: str = "manual"
    case_id: Optional[str] = None
    issue_id: Optional[str] = None
    hypothesis_id: Optional[str] = None
    cited_result_id: Optional[str] = None
    cited_doc_id: Optional[str] = None
    cited_span: Optional[CitedSpan] = None
    evidence_edge_status: str = EVIDENCE_EDGE_NOT_ASSESSED
    machine_status: str = MACHINE_STATUS_CANDIDATE
    human_status: str = HUMAN_STATUS_PENDING
    created_at: str = ""

    def __post_init__(self) -> None:
        # Construction-path enforcement, mirroring ``EvidenceAuditRow``: a claim that
        # cannot be represented honestly must not be representable at all.
        self.validate()

    def validate(self) -> None:
        """Raise ``ValueError`` when the claim record contradicts §6.8."""

        for name in ("claim_id", "run_id", "source_text_hash", "claim_text"):
            if _is_blank(getattr(self, name)):
                raise ValueError(f"claim_record.{name} must be non-blank (DATA_SCHEMA.md §6.8)")
        if self.claim_type not in CLAIM_TYPES:
            raise ValueError(
                f"claim_record.claim_type {self.claim_type!r} is not one of {list(CLAIM_TYPES)} "
                "(DATA_SCHEMA.md §6.8)"
            )
        if self.decomposition_method not in DECOMPOSITION_METHODS:
            raise ValueError(
                f"claim_record.decomposition_method {self.decomposition_method!r} is not one of "
                f"{list(DECOMPOSITION_METHODS)} (DATA_SCHEMA.md §6.8)"
            )
        if self.machine_status not in (
            MACHINE_STATUS_EXTRACTED,
            MACHINE_STATUS_CANDIDATE,
            MACHINE_STATUS_UNKNOWN,
        ):
            raise ValueError(f"claim_record.machine_status {self.machine_status!r} is not allowed")
        if self.human_status not in (
            HUMAN_STATUS_PENDING,
            HUMAN_STATUS_CONFIRMED,
            HUMAN_STATUS_NA,
        ):
            raise ValueError(f"claim_record.human_status {self.human_status!r} is not allowed")
        if self.evidence_edge_status not in EVIDENCE_EDGE_STATUSES:
            raise ValueError(
                f"claim_record.evidence_edge_status {self.evidence_edge_status!r} is not one of "
                f"{list(EVIDENCE_EDGE_STATUSES)} (DATA_SCHEMA.md §6.8)"
            )
        if self.hypothesis_id is not None and not HYPOTHESIS_ID_PATTERN.match(self.hypothesis_id):
            raise ValueError(
                f"claim_record.hypothesis_id {self.hypothesis_id!r} must be '<case_id>-H<n>'; "
                "'H?' / 'HX' are query-time markers and are never instantiated as hypotheses "
                "(DATA_SCHEMA.md §6.8)"
            )
        if self.cited_span is not None:
            if not isinstance(self.cited_span, CitedSpan):
                raise ValueError(
                    "claim_record.cited_span must be a CitedSpan "
                    f"({type(self.cited_span).__name__} given)"
                )
            self.cited_span.validate()
        if self.evidence_edge_status == EVIDENCE_EDGE_LINKED:
            missing = [name for name in _EDGE_FIELDS if _is_blank(getattr(self, name))]
            if missing:
                raise ValueError(
                    "claim_record.evidence_edge_status='linked' requires all of "
                    f"cited_result_id + cited_doc_id + cited_span; missing {missing} "
                    "(DATA_SCHEMA.md §6.8)"
                )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EdgeResolution:
    """Outcome of checking one claim's evidence edge against a run's results."""

    claim_id: str
    status: str
    reasons: Tuple[str, ...] = ()

    @property
    def is_linked(self) -> bool:
        return self.status == EVIDENCE_EDGE_LINKED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _result_index(results: Any) -> Dict[str, Any]:
    if isinstance(results, Mapping):
        return dict(results)
    return {item.result_id: item for item in results}


def _extent_index(text_versions: Any) -> Mapping[str, Any]:
    if isinstance(text_versions, Mapping):
        return text_versions
    return {version.text_version_id: version for version in text_versions}


def resolve_evidence_edge(
    claim: ClaimRecord,
    *,
    results: Any,
    text_versions: Mapping[str, Any],
) -> EdgeResolution:
    """Decide whether ``claim`` has a valid ``linked`` evidence edge.

    ``results`` is a mapping ``result_id -> RetrievalResult`` or a sequence of
    results; ``text_versions`` maps ``text_version_id`` to any record exposing
    ``doc_id`` and ``char_length`` (a ``DocumentTextVersion`` or a
    :class:`TextVersionExtent`).

    Rules (``DATA_SCHEMA.md`` §6.8, ``EVIDENCE_AUDIT_DESIGN.md`` §8):

    * no edge members at all -> ``not_assessed`` (the check was never run);
    * some but not all members -> ``unlinked``;
    * the cited result must exist in this run;
    * ``cited_doc_id`` must equal the cited result's ``doc_id``;
    * ``cited_span.text_version_id`` must be the cited result's text version, that
      version must belong to the cited doc, and the span must lie inside it.
    """

    members = {name: getattr(claim, name) for name in _EDGE_FIELDS}
    present = [name for name, value in members.items() if not _is_blank(value)]
    if not present:
        return EdgeResolution(
            claim.claim_id,
            EVIDENCE_EDGE_NOT_ASSESSED,
            ("no evidence edge was built for this claim",),
        )
    missing = [name for name in _EDGE_FIELDS if name not in present]
    if missing:
        return EdgeResolution(
            claim.claim_id,
            EVIDENCE_EDGE_UNLINKED,
            (
                f"incomplete evidence edge: {missing} missing; linked requires "
                "cited_result_id + cited_doc_id + cited_span (DATA_SCHEMA.md §6.8)",
            ),
        )

    span = claim.cited_span
    result = _result_index(results).get(claim.cited_result_id)
    if result is None:
        return EdgeResolution(
            claim.claim_id,
            EVIDENCE_EDGE_UNLINKED,
            (
                f"cited_result_id {claim.cited_result_id!r} is not a retrieval_result of this run; "
                "an evidence edge must point at a specific retrieval result",
            ),
        )

    reasons: List[str] = []
    if claim.cited_doc_id != result.doc_id:
        reasons.append(
            f"cited_doc_id {claim.cited_doc_id!r} != doc_id {result.doc_id!r} of the cited result "
            f"{claim.cited_result_id!r}"
        )
    if span.text_version_id != result.text_version_id:
        reasons.append(
            f"cited_span.text_version_id {span.text_version_id!r} != text_version_id "
            f"{result.text_version_id!r} of the cited result"
        )

    extent = _extent_index(text_versions).get(span.text_version_id)
    if extent is None:
        reasons.append(
            f"cited_span.text_version_id {span.text_version_id!r} is not a known "
            "document_text_version"
        )
    else:
        if extent.doc_id != result.doc_id:
            reasons.append(
                f"text version {span.text_version_id!r} belongs to {extent.doc_id!r}, not to the "
                f"cited result's doc {result.doc_id!r}"
            )
        if span.span_end > int(extent.char_length):
            reasons.append(
                f"cited_span [{span.span_start}, {span.span_end}) exceeds the text version length "
                f"{int(extent.char_length)}"
            )

    if reasons:
        return EdgeResolution(claim.claim_id, EVIDENCE_EDGE_UNLINKED, tuple(reasons))
    return EdgeResolution(claim.claim_id, EVIDENCE_EDGE_LINKED, ())


def resolve_claim_edges(
    claims: Sequence[ClaimRecord],
    *,
    results: Any,
    text_versions: Mapping[str, Any],
) -> Dict[str, EdgeResolution]:
    """Resolve every claim's edge once; keyed by ``claim_id``."""

    resolutions: Dict[str, EdgeResolution] = {}
    for claim in claims:
        if claim.claim_id in resolutions:
            raise ValueError(f"duplicate claim_id {claim.claim_id!r} in the same audit batch")
        resolutions[claim.claim_id] = resolve_evidence_edge(
            claim, results=results, text_versions=text_versions
        )
    return resolutions


def resolved_claim(claim: ClaimRecord, resolution: EdgeResolution) -> ClaimRecord:
    """Return ``claim`` with the resolved ``evidence_edge_status`` recorded."""

    if resolution.claim_id != claim.claim_id:
        raise ValueError(
            f"edge resolution for {resolution.claim_id!r} does not belong to claim "
            f"{claim.claim_id!r}"
        )
    return replace(claim, evidence_edge_status=resolution.status)


@dataclass(frozen=True)
class EntailmentJudgement:
    """A D5 verdict produced by an *actually executed* method (§4.1, §5.2).

    ``probabilities`` is mandatory for ``nli_model``; ``supported`` requires human
    confirmation (``EVIDENCE_AUDIT_DESIGN.md`` §4.2.1, §7.4), so a machine-only
    verdict can never be recorded as ``supported``.
    """

    claim_id: str
    status: str
    method: str = "nli_model"
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    probabilities: Optional[Mapping[str, float]] = None
    prompt_hash: Optional[str] = None
    human_reviewed: bool = False
    review_id: Optional[str] = None
    annotator_id: Optional[str] = None
    review_note: Optional[str] = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if _is_blank(self.claim_id):
            raise ValueError("EntailmentJudgement.claim_id must be non-blank")
        if self.status not in D5_EVALUATED_STATUSES:
            raise ValueError(
                f"D5 status {self.status!r} is not one of {list(D5_EVALUATED_STATUSES)}; a missing "
                "check is recorded as not_assessed by the builder, never as a judgement "
                "(DATA_SCHEMA.md §6.9)"
            )
        if self.method not in D5_METHODS:
            raise ValueError(
                f"D5 method {self.method!r} is not one of {list(D5_METHODS)} (DATA_SCHEMA.md §6.9)"
            )
        if self.method in ("nli_model", "llm_assist"):
            missing = [
                name
                for name in ("model_id", "model_version")
                if _is_blank(getattr(self, name))
            ]
            if missing:
                raise ValueError(
                    f"D5 method {self.method!r} requires non-blank {missing} "
                    "(DATA_SCHEMA.md §6.9; EVIDENCE_AUDIT_DESIGN.md §4.1)"
                )
        if self.method == "nli_model":
            if not self.probabilities:
                raise ValueError(
                    "D5 method 'nli_model' requires the model's probabilities in detail "
                    "(EVIDENCE_AUDIT_DESIGN.md §5.2)"
                )
            for name, value in self.probabilities.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"probability {name!r} must be numeric, got {value!r}")
                if not 0.0 <= float(value) <= 1.0:
                    raise ValueError(f"probability {name!r} must be in [0, 1], got {value!r}")
        if self.status == "supported" and not self.human_reviewed:
            raise ValueError(
                "a D5 'supported' conclusion must be human-confirmed; a machine verdict may only "
                "be recorded as refuted / not_enough_info or left not_assessed "
                "(EVIDENCE_AUDIT_DESIGN.md §4.2.1, §7.4)"
            )
        if self.method == "human_review" and not self.human_reviewed:
            raise ValueError("D5 method 'human_review' must set human_reviewed=True")
        review_fields = {"review_id": self.review_id, "annotator_id": self.annotator_id, "review_note": self.review_note}
        supplied = [name for name, value in review_fields.items() if not _is_blank(value)]
        if self.human_reviewed:
            missing = [name for name in review_fields if name not in supplied]
            if missing:
                raise ValueError(
                    f"human_reviewed=True requires non-blank {missing} "
                    "(DATA_SCHEMA.md §6.9 「人工追溯约束」)"
                )
        elif supplied:
            raise ValueError(
                f"a machine D5 judgement must not carry reviewer fields {supplied} "
                "(DATA_SCHEMA.md §6.9)"
            )


def validate_evidence_audit_row(row: EvidenceAuditRow) -> None:
    """Enforce ``DATA_SCHEMA.md`` §6.9 target rules on one ``evidence_audit`` row.

    * 「目标互斥约束」: ``target_type=retrieval_result`` carries ``result_id`` and no
      ``claim_id``; ``target_type=claim`` carries ``claim_id`` and no ``result_id``.
      Both keys empty or both filled is forbidden.
    * 「维度目标约束」: a ``claim`` target is only allowed for ``claim_entailment``;
      the other four dimensions must target a ``retrieval_result``.
    """

    if row.target_type not in EVIDENCE_TARGET_TYPES:
        raise ValueError(
            f"evidence_audit.target_type {row.target_type!r} is not one of "
            f"{list(EVIDENCE_TARGET_TYPES)} (DATA_SCHEMA.md §6.9)"
        )
    has_result = not _is_blank(row.result_id)
    has_claim = not _is_blank(row.claim_id)
    if row.target_type == "claim":
        if not has_claim or has_result:
            raise ValueError(
                f"evidence_audit target_type='claim' requires claim_id and a NULL result_id "
                f"(claim_id={row.claim_id!r}, result_id={row.result_id!r}); "
                "DATA_SCHEMA.md §6.9 「目标互斥约束」"
            )
        if row.dimension != CLAIM_SCOPED_DIMENSION:
            raise ValueError(
                f"evidence_audit target_type='claim' only allows dimension="
                f"{CLAIM_SCOPED_DIMENSION!r}, got {row.dimension!r}; a retrieval result is not a "
                "claim (DATA_SCHEMA.md §6.9 「维度目标约束」)"
            )
        return
    if not has_result or has_claim:
        raise ValueError(
            f"evidence_audit target_type='retrieval_result' requires result_id and a NULL "
            f"claim_id (result_id={row.result_id!r}, claim_id={row.claim_id!r}); "
            "DATA_SCHEMA.md §6.9 「目标互斥约束」"
        )
    if row.dimension not in RESULT_SCOPED_DIMENSIONS:
        raise ValueError(
            f"evidence_audit dimension {row.dimension!r} must target a claim, not a retrieval "
            f"result; allowed result-scoped dimensions: {list(RESULT_SCOPED_DIMENSIONS)} "
            "(DATA_SCHEMA.md §6.9 「维度目标约束」)"
        )


def _d5_row(
    claim: ClaimRecord,
    judgement: Optional[EntailmentJudgement],
    audited_at: str,
) -> EvidenceAuditRow:
    """Build the D5 row of a claim whose evidence edge is ``linked``."""

    span = claim.cited_span
    detail: Dict[str, Any] = {
        "claim_id": claim.claim_id,
        "claim_text": claim.claim_text,
        "claim_type": claim.claim_type,
        "evidence_edge_status": EVIDENCE_EDGE_LINKED,
        "cited_result_id": claim.cited_result_id,
        "cited_doc_id": claim.cited_doc_id,
        "cited_span": span.to_dict(),
    }

    if judgement is None:
        detail.update(
            {
                "model_id": None,
                "model_version": None,
                "probabilities": None,
                "human_reviewed": False,
                "reason": (
                    "证据边合法（linked），但本运行未提供 NLI/人工判定：D5=not_assessed，"
                    "不得以规则兜底伪造 supported/refuted（EVIDENCE_AUDIT_DESIGN.md §1.3, §4.2.3）"
                ),
            }
        )
        row = EvidenceAuditRow(
            dimension=CLAIM_SCOPED_DIMENSION,
            status=NOT_ASSESSED,
            method="nli_model",
            target_type="claim",
            claim_id=claim.claim_id,
            result_id=None,
            audited_at=audited_at,
            detail=detail,
        )
        validate_evidence_audit_row(row)
        return row

    if judgement.claim_id != claim.claim_id:
        raise ValueError(
            f"entailment judgement for {judgement.claim_id!r} does not belong to claim "
            f"{claim.claim_id!r}"
        )
    detail.update(
        {
            "model_id": judgement.model_id,
            "model_version": judgement.model_version,
            "probabilities": dict(judgement.probabilities) if judgement.probabilities else None,
            "human_reviewed": judgement.human_reviewed,
            "reason": (
                "D5 由实际执行的方法产出；机器结论仅为 machine_candidate 证据，不构成法律结论，"
                "也不得与 D1–D4 合并为综合分（EVIDENCE_AUDIT_DESIGN.md §4.2.1, §5.2）"
            ),
        }
    )
    row = EvidenceAuditRow(
        dimension=CLAIM_SCOPED_DIMENSION,
        status=judgement.status,
        method=judgement.method,
        target_type="claim",
        claim_id=claim.claim_id,
        result_id=None,
        model_id=judgement.model_id,
        model_version=judgement.model_version,
        prompt_hash=judgement.prompt_hash,
        audited_at=audited_at,
        human_confirmed=HUMAN_CONFIRMED_TRUE if judgement.human_reviewed else HUMAN_CONFIRMED_NOT_REVIEWED,
        review_id=judgement.review_id,
        annotator_id=judgement.annotator_id,
        review_note=judgement.review_note,
        detail=detail,
    )
    validate_evidence_audit_row(row)
    return row


def build_claim_evidence_audit(
    claims: Sequence[ClaimRecord],
    *,
    results: Any,
    text_versions: Mapping[str, Any],
    audited_at: str,
    entailments: Optional[Mapping[str, EntailmentJudgement]] = None,
) -> List[EvidenceAuditRow]:
    """Return the D5 rows that the claims' evidence edges actually support.

    * a claim whose edge is not ``linked`` gets **no** D5 row — the closure rule
      forbids a ``claim_entailment`` row without ``cited_result_id + cited_doc_id +
      cited_span`` (``DATA_SCHEMA.md`` §6.9 「主张—证据闭合约束」, §8);
    * a ``linked`` claim with no supplied judgement gets ``not_assessed`` — the honest
      record of a dimension that was not run;
    * handing in a judgement for an unlinked (or unknown) claim raises ``ValueError``
      instead of being quietly dropped, so no fabricated entailment can be persisted.

    ``audited_at`` is the caller's timestamp; this function never reads the clock, so
    a batch stays reproducible.
    """

    entailments = dict(entailments or {})
    by_id: Dict[str, ClaimRecord] = {}
    for claim in claims:
        if claim.claim_id in by_id:
            raise ValueError(f"duplicate claim_id {claim.claim_id!r} in the same audit batch")
        by_id[claim.claim_id] = claim

    unknown = sorted(set(entailments) - set(by_id))
    if unknown:
        raise ValueError(f"entailment judgements reference unknown claims {unknown}")

    resolutions = resolve_claim_edges(claims, results=results, text_versions=text_versions)

    rows: List[EvidenceAuditRow] = []
    for claim in claims:
        resolution = resolutions[claim.claim_id]
        judgement = entailments.get(claim.claim_id)
        if resolution.status != EVIDENCE_EDGE_LINKED:
            if judgement is not None:
                raise ValueError(
                    f"claim_entailment for {claim.claim_id!r} must not be recorded: "
                    f"evidence_edge_status={resolution.status!r} "
                    f"({'; '.join(resolution.reasons)}); D5 只允许建立在合法证据边上 "
                    "(DATA_SCHEMA.md §6.9 「主张—证据闭合约束」)"
                )
            continue
        rows.append(_d5_row(claim, judgement, audited_at))
    return rows
