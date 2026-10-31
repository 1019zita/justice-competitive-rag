"""Independent runtime authority and applicability audit contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


AUTHORITY_STATUSES = ("verified", "plausible", "unknown", "unavailable")
SOURCE_IDENTITY_STATUSES = ("verified", "unknown", "unavailable")
AUTHORITY_LEVELS = (
    "statute",
    "judicial_interpretation",
    "guiding_case",
    "typical_case",
    "court_judgment",
    "policy_document",
    "academic_source",
    "commercial_summary",
    "other",
    "unknown",
)
VALIDITY_STATUSES = (
    "in_force",
    "amended",
    "repealed",
    "superseded",
    "historical",
    "unknown",
    "not_assessed",
)
APPLICABILITY_STATUSES = (
    "directly_relevant",
    "supportive_reference",
    "limited",
    "uncertain",
    "not_applicable",
    "unavailable",
)
FIT_STATUSES = ("fit", "mismatch", "unknown", "not_assessed")


@dataclass(frozen=True)
class AuthorityAuditResult:
    status: str
    source_identity_status: str
    authority_level: str
    validity_status: str
    publisher: Optional[str]
    reason: str
    provenance_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApplicabilityAuditResult:
    status: str
    issue_relevance: str
    jurisdiction_fit: str
    temporal_fit: str
    factual_legal_fit: str
    reason: str
    provenance_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceAuditBundle:
    evidence_id: str
    authority: AuthorityAuditResult
    applicability: ApplicabilityAuditResult

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "authority": self.authority.to_dict(),
            "applicability": self.applicability.to_dict(),
        }
