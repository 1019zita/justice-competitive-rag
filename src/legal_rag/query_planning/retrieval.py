"""Dynamic shared-corpus competitive retrieval over CV-0005."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..corpus_loader import CorpusSnapshot, load_corpus
from ..data import REPO_ROOT, sha256_file
from ..models import SourceDocument
from ..retrieval import SparseTfidfIndex


RUNTIME_SCOPE_NAME = "dynamic_shared_corpus_runtime"
RUNTIME_SCOPE_MODE = "shared_runtime"
RETRIEVAL_VERSION = "DYNAMIC_SPARSE_COMPETITIVE_V1"
ROUTE_NAMES = ("neutral", "support", "counter")


@dataclass(frozen=True)
class DynamicRetrievedChunk:
    evidence_id: str
    issue_id: str
    retrieval_id: str
    query_id: str
    query: str
    retrieval_route: str
    rank: int
    score: float
    doc_id: str
    chunk_id: str
    source_scope_id: str
    text_version_id: str
    title: str
    source_origin: str
    source_url: Optional[str]
    publication_date: Optional[str]
    document_type: str
    document_type_as_written: str
    authority_role: str
    authority_tier: str
    publisher: Optional[str]
    source_database: Optional[str]
    validity_status: str
    jurisdiction: str
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DynamicRetrievalTrace:
    retrieval_id: str
    query_id: str
    issue_id: str
    query: str
    retrieval_route: str
    result_ids: List[str]
    corpus_version: str
    corpus_manifest_hash: str
    scope_name: str
    scope_mode: str
    index_version: str
    excluded_doc_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SharedCorpusRuntime:
    snapshot: CorpusSnapshot
    index: SparseTfidfIndex
    documents_by_id: Mapping[str, SourceDocument]
    corpus_manifest_hash: str
    excluded_doc_ids: Tuple[str, ...]


@lru_cache(maxsize=4)
def _load_runtime(
    corpus_dir: str,
    excluded_doc_ids: Tuple[str, ...],
) -> SharedCorpusRuntime:
    snapshot = load_corpus(corpus_dir)
    excluded = set(excluded_doc_ids)
    documents = [item for item in snapshot.indexed_documents if item.doc_id not in excluded]
    chunks = [item for item in snapshot.chunks if item.doc_id not in excluded]
    index = SparseTfidfIndex(
        documents=documents,
        chunks=chunks,
        corpus_version=snapshot.corpus_version,
        index_version=snapshot.index_version,
    )
    manifest_hash = sha256_file(Path(snapshot.corpus_dir) / "manifest.json")
    return SharedCorpusRuntime(
        snapshot=snapshot,
        index=index,
        documents_by_id={item.doc_id: item for item in documents},
        corpus_manifest_hash=manifest_hash,
        excluded_doc_ids=tuple(sorted(excluded)),
    )


class DynamicCompetitiveRetriever:
    """Run three independent retrieval intents against one bounded shared index."""

    def __init__(
        self,
        *,
        corpus_dir: str | Path = "corpus_expansion/CV-0005",
        top_k_per_route: int = 2,
        exclude_doc_ids: Sequence[str] = (),
    ) -> None:
        path = Path(corpus_dir)
        if not path.is_absolute():
            path = REPO_ROOT / path
        self.runtime = _load_runtime(str(path), tuple(sorted(set(exclude_doc_ids))))
        self.top_k_per_route = max(1, int(top_k_per_route))

    def retrieve(self, plan: DynamicQueryPlan) -> Tuple[List[DynamicRetrievedChunk], List[DynamicRetrievalTrace]]:
        evidence: List[DynamicRetrievedChunk] = []
        traces: List[DynamicRetrievalTrace] = []
        for issue_plan in plan.issue_plans:
            for planned_query in issue_plan.queries:
                query_id = self._query_id(planned_query)
                retrieval_id = f"{query_id}:retrieval"
                scores = self.runtime.index.score(planned_query.query)
                ranked_indices = sorted(
                    range(len(scores)),
                    key=lambda index: (-float(scores[index]), self.runtime.index.chunks[index].chunk_id),
                )[: self.top_k_per_route]
                result_ids: List[str] = []
                for rank, chunk_index in enumerate(ranked_indices, start=1):
                    chunk = self.runtime.index.chunks[chunk_index]
                    document = self.runtime.documents_by_id.get(chunk.doc_id)
                    if document is None:
                        continue
                    evidence_id = f"EV-{len(evidence) + 1:04d}"
                    result_ids.append(evidence_id)
                    evidence.append(
                        DynamicRetrievedChunk(
                            evidence_id=evidence_id,
                            issue_id=planned_query.issue_id,
                            retrieval_id=retrieval_id,
                            query_id=query_id,
                            query=planned_query.query,
                            retrieval_route=planned_query.route,
                            rank=rank,
                            score=round(float(scores[chunk_index]), 8),
                            doc_id=chunk.doc_id,
                            chunk_id=chunk.chunk_id,
                            source_scope_id=chunk.source_scope_id,
                            text_version_id=chunk.text_version_id,
                            title=document.title,
                            source_origin=self._source_origin(document),
                            source_url=self._source_url(document),
                            publication_date=document.publication_date or document.judgment_date,
                            document_type=document.document_type,
                            document_type_as_written=document.document_type_as_written,
                            authority_role=document.authority_role,
                            authority_tier=document.authority_tier,
                            publisher=document.source_authority if document.source_authority not in {"", "UNKNOWN", "unknown"} else None,
                            source_database=document.source_database if document.source_database not in {"", "UNKNOWN", "unknown"} else None,
                            validity_status=document.validity_status,
                            jurisdiction=document.jurisdiction,
                            text=chunk.chunk_text,
                        )
                    )
                traces.append(
                    DynamicRetrievalTrace(
                        retrieval_id=retrieval_id,
                        query_id=query_id,
                        issue_id=planned_query.issue_id,
                        query=planned_query.query,
                        retrieval_route=planned_query.route,
                        result_ids=result_ids,
                        corpus_version=self.runtime.snapshot.corpus_version,
                        corpus_manifest_hash=self.runtime.corpus_manifest_hash,
                        scope_name=RUNTIME_SCOPE_NAME,
                        scope_mode=RUNTIME_SCOPE_MODE,
                        index_version=self.runtime.index.index_version,
                        excluded_doc_ids=list(self.runtime.excluded_doc_ids),
                    )
                )
        return evidence, traces

    @staticmethod
    def _query_id(query: PlannedQuery) -> str:
        digest = hashlib.sha256(
            f"{query.issue_id}|{query.route}|{query.query}".encode("utf-8")
        ).hexdigest()[:12]
        return f"DYN-Q-{digest}"

    @staticmethod
    def _source_origin(document: SourceDocument) -> str:
        return document.source_authority or document.source_database or document.source_scope_id

    @staticmethod
    def _source_url(document: SourceDocument) -> Optional[str]:
        value = document.official_url or document.discovery_url
        return value if value and value != "UNKNOWN" else None


__all__ = [
    "DynamicCompetitiveRetriever",
    "DynamicRetrievedChunk",
    "DynamicRetrievalTrace",
    "RETRIEVAL_VERSION",
    "RUNTIME_SCOPE_MODE",
    "RUNTIME_SCOPE_NAME",
]
