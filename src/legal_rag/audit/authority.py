"""Metadata-only source identity and authority screening."""
from __future__ import annotations

from typing import Any, List, Optional

from ..query_planning.retrieval import DynamicRetrievedChunk
from .models import AuthorityAuditResult


UNKNOWN_VALUES = {"", "UNKNOWN", "unknown", "未提供", "未核查", None}


def _present(value: Any) -> bool:
    return value not in UNKNOWN_VALUES and bool(str(value).strip())


def _authority_level(item: DynamicRetrievedChunk) -> str:
    text = " ".join(
        str(value or "").lower()
        for value in (
            item.document_type,
            getattr(item, "document_type_as_written", ""),
            item.authority_role,
            item.title,
        )
    )
    if any(token in text for token in ("指导性案例", "guiding")):
        return "guiding_case"
    if any(token in text for token in ("司法解释", "judicial interpretation")):
        return "judicial_interpretation"
    if any(token in text for token in ("法律", "法规", "条例", "规章", "statute", "regulation")):
        return "statute"
    if any(token in text for token in ("裁判", "判决", "裁定", "judgment")):
        return "court_judgment"
    if any(token in text for token in ("政策", "通知", "policy")):
        return "policy_document"
    if any(token in text for token in ("学术", "论文", "academic")):
        return "academic_source"
    return "unknown"


def audit_authority(item: DynamicRetrievedChunk) -> AuthorityAuditResult:
    """Return a conservative result; never promote a host to a publisher."""
    try:
        fields: List[str] = []
        if _present(item.doc_id):
            fields.append("document_id")
        if _present(item.title):
            fields.append("source_title")
        if _present(item.source_origin):
            fields.append("source_origin")
        publisher = getattr(item, "publisher", None)
        if _present(publisher):
            fields.append("publisher")
        if _present(item.document_type):
            fields.append("document_type")
        validity = str(getattr(item, "validity_status", "unknown") or "unknown")
        if validity in {"in_force", "amended", "repealed", "superseded", "historical"}:
            fields.append("validity_status")
        else:
            validity = "unknown"
        level = _authority_level(item)
        identity_ok = all(_present(value) for value in (item.doc_id, item.title, item.source_origin))
        if not identity_ok:
            return AuthorityAuditResult(
                status="unknown",
                source_identity_status="unknown",
                authority_level=level,
                validity_status=validity,
                publisher=str(publisher) if _present(publisher) else None,
                reason="来源身份字段不完整，未将检索宿主解释为发布主体。",
                provenance_fields=fields,
            )
        if _present(publisher) and level != "unknown":
            status = "verified"
            reason = "document identity、publisher 和 document type 均来自当前 corpus metadata。"
        elif level != "unknown":
            status = "plausible"
            reason = "文书类型和来源身份可识别，但 publisher 缺失；未将 host/database 当作权威机关。"
        else:
            status = "unknown"
            reason = "来源身份可见，但 authority level 或 publisher 不足以确认。"
        return AuthorityAuditResult(
            status=status,
            source_identity_status="verified",
            authority_level=level,
            validity_status=validity,
            publisher=str(publisher) if _present(publisher) else None,
            reason=reason,
            provenance_fields=fields,
        )
    except Exception as exc:  # noqa: BLE001
        return AuthorityAuditResult(
            status="unavailable",
            source_identity_status="unavailable",
            authority_level="unknown",
            validity_status="not_assessed",
            publisher=None,
            reason=f"authority audit unavailable: {type(exc).__name__}",
            provenance_fields=[],
        )


__all__ = ["audit_authority"]
