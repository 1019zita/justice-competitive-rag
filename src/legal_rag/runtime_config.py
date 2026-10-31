"""Single source of truth for formal runtime corpus selection.

The frozen workbook remains the L2 case/issue/hypothesis input. Formal runtime
entrypoints must use the acquired CV-0005 L1 corpus through this module. CV-0004
is retained as the immutable superseded predecessor. The historical
metadata-only constructor remains available only when a caller explicitly
chooses ``LegalRAGPipeline.from_frozen_cases``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .corpus_loader import CorpusSnapshot, load_corpus
from .data import REPO_ROOT, sha256_file

CANONICAL_CORPUS_VERSION = "CV-0005"
CANONICAL_CORPUS_DIR = REPO_ROOT / "corpus_expansion" / CANONICAL_CORPUS_VERSION
CANONICAL_MANIFEST_NAME = "manifest.json"

#: Current-facing discovery-host semantics, verified from acquisition/retrieval
#: provenance (not the historical CV-0003 expansion-round 1/17 count).
#: The four P2 secondary hosts are NOT counted as attempted: their
#: ACCESS_BLOCKED rows are administrative ("按决策暂不执行"), with no real
#: search payload, result count or access log.
DISCOVERY_HOST_SEMANTICS: Dict[str, int] = {
    "discovery_hosts_authorized": 17,
    "discovery_hosts_attempted": 9,
    "discovery_hosts_successfully_searched": 3,
    "contributing_hosts": 3,
    "canonical_documents_from_authorized_hosts": 507,
    "discovery_hosts_blocked_or_failed": 6,
    "discovery_hosts_not_attempted": 8,
    "discovery_hosts_out_of_scope": 1,
}


class CanonicalRuntimeError(RuntimeError):
    """The formal runtime corpus is missing or is not the canonical version."""


def canonical_corpus_manifest_path() -> Path:
    return CANONICAL_CORPUS_DIR / CANONICAL_MANIFEST_NAME


def canonical_corpus_manifest_hash() -> str:
    path = canonical_corpus_manifest_path()
    if not path.is_file():
        raise FileNotFoundError(f"canonical corpus manifest missing: {path}")
    return sha256_file(path)


def load_canonical_corpus() -> CorpusSnapshot:
    """Load CV-0005 and fail closed on any mismatch or integrity error."""

    snapshot = load_corpus(CANONICAL_CORPUS_DIR)
    if snapshot.corpus_version != CANONICAL_CORPUS_VERSION:
        raise CanonicalRuntimeError(
            f"canonical runtime requires {CANONICAL_CORPUS_VERSION}, "
            f"loaded {snapshot.corpus_version!r}"
        )
    return snapshot


def canonical_runtime_identity(snapshot: Optional[CorpusSnapshot] = None) -> Dict[str, Any]:
    """Return machine-readable identity and counts for UI/CLI display."""

    snapshot = snapshot or load_canonical_corpus()
    if snapshot.corpus_version != CANONICAL_CORPUS_VERSION:
        raise CanonicalRuntimeError(
            f"canonical runtime identity requires {CANONICAL_CORPUS_VERSION}, "
            f"loaded {snapshot.corpus_version!r}"
        )
    manifest_path = Path(snapshot.corpus_dir) / CANONICAL_MANIFEST_NAME
    manifest_hash = sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = manifest.get("counts") or {}
    return {
        "corpus_version": snapshot.corpus_version,
        "corpus_manifest_id": f"{snapshot.corpus_version}@{manifest_hash}",
        "corpus_manifest_hash": manifest_hash,
        "manifest_path": str(manifest_path).replace("\\", "/"),
        "documents_total": counts.get("total", len(snapshot.documents)),
        "documents_indexed": len(snapshot.indexed_documents),
        "full_text": counts.get("full_text", counts.get("acquired", len(snapshot.indexed_documents))),
        "metadata_only": counts.get("metadata_only", len(snapshot.absent_documents)),
        "chunks": len(snapshot.chunks),
        "canonical_build_complete": snapshot.corpus_version == CANONICAL_CORPUS_VERSION,
        "query_group_coverage_complete": "14/14",
        **DISCOVERY_HOST_SEMANTICS,
        "discovery_complete_historical": bool(manifest.get("discovery_complete")),
    }


def load_canonical_pipeline(config=None):
    """Build the formal pipeline from the validated canonical corpus only."""

    from .pipeline import LegalRAGPipeline

    snapshot = load_canonical_corpus()
    return LegalRAGPipeline.from_corpus(
        snapshot.corpus_dir,
        config=config,
    )


__all__ = [
    "CANONICAL_CORPUS_DIR",
    "CANONICAL_CORPUS_VERSION",
    "DISCOVERY_HOST_SEMANTICS",
    "CanonicalRuntimeError",
    "canonical_corpus_manifest_hash",
    "canonical_corpus_manifest_path",
    "canonical_runtime_identity",
    "load_canonical_corpus",
    "load_canonical_pipeline",
]
