"""Reader for the *acquired* full-text corpus written by :mod:`legal_rag.acquire`.

``legal_rag.data.build_source_documents`` is the frozen **metadata-only** loader:
it turns every frozen source authority into a document whose text version is the
verbatim authority title (``corpus_version = CV-0001``).  This module is the
other half: it reads back the artefacts of a **real acquisition run** — the raw
archive index, the normalizer output, the versioned chunks and the manifest —
and reconstructs the same dataclasses the retrieval slice consumes
(:class:`~legal_rag.models.SourceDocument`,
:class:`~legal_rag.models.DocumentTextVersion`,
:class:`~legal_rag.models.VersionedChunk`), so the canonical pipeline can be
pointed at real full text instead of at titles.

Hard rules enforced here (never relaxed, never repaired silently)
----------------------------------------------------------------
* **Nothing is fabricated.**  Only bytes already on disk are read.  A source
  whose acquisition failed has no text version and therefore no chunk: it stays
  ``ingest_status="metadata_only"`` and is reported as *absent*.
* **Nothing is backfilled.**  A missing chunk file for an ``ACQUIRED`` source,
  a hash mismatch, a span that does not slice back to its own ``chunk_text``, or
  a manifest/document/version count disagreement raises
  :class:`CorpusIntegrityError` instead of producing a partial corpus.
* **Provenance is carried, not summarised away.**  ``corpus_version``,
  ``ingest_status``, ``authority_role``, per-document
  ``document_authority.classification`` (from the manifest), the raw/normalized
  artefact hashes and the recorded failure codes are all preserved; the manifest
  source entries are kept verbatim in :attr:`CorpusSnapshot.source_records`.

The discovery-host rule (``docs/02_design``): a *host* is never a legal
authority.  Authority is classified per document in the manifest and is read
from there, never inferred from the host name.
"""

from __future__ import annotations

import json
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Type, TypeVar

from .data import REPO_ROOT, now_iso, sha256_text
from .models import UNKNOWN, DocumentTextVersion, SourceDocument, VersionedChunk

CORPUS_READER_VERSION = "corpus-reader-0.1"

#: Canonical location of the acquired corpus (relative to the repository root).
DEFAULT_CORPUS_DIR = "corpus"

MANIFEST_FILE = "manifest.json"
DOCUMENTS_FILE = "documents.json"
TEXT_VERSIONS_FILE = "text_versions.json"
CHUNKS_DIRNAME = "chunks"

INGEST_FULL_TEXT = "full_text"
INGEST_METADATA_ONLY = "metadata_only"

#: Status written by the acquirer for a source whose text was fetched and
#: version-checked.  Any other status means "no text version exists".
STATUS_ACQUIRED = "ACQUIRED"

Record = TypeVar("Record")


class CorpusIntegrityError(RuntimeError):
    """The on-disk corpus is internally inconsistent (never silently repaired)."""


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"语料文件不存在: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:  # pragma: no cover - defensive
        raise CorpusIntegrityError(f"{path}: JSON 解析失败: {error}") from error


def _record_from_dict(cls: Type[Record], payload: Dict[str, Any], origin: str) -> Record:
    """Strict dataclass reconstruction: unknown or missing fields are an error.

    A schema drift between the writer (:mod:`legal_rag.acquire`) and this reader
    must fail loudly; silently dropping a field would lose provenance.
    """
    known = {item.name for item in fields(cls)}
    unknown = sorted(set(payload) - known)
    if unknown:
        raise CorpusIntegrityError(f"{origin}: {cls.__name__} 出现未知字段 {unknown}")
    missing = sorted(
        item.name
        for item in fields(cls)
        if item.default is MISSING
        and item.default_factory is MISSING  # type: ignore[misc]
        and item.name not in payload
    )
    if missing:
        raise CorpusIntegrityError(f"{origin}: {cls.__name__} 缺少字段 {missing}")
    return cls(**payload)


@dataclass
class CorpusSnapshot:
    """Everything read back from one acquired-corpus directory."""

    corpus_dir: str
    corpus_version: str
    frozen_corpus_version: str
    manifest_version: str
    acquisition_version: str
    normalizer_version: str
    chunker_version: str
    index_version: str
    generated_at: str
    manifest_counts: Dict[str, Any]
    documents: List[SourceDocument]
    text_versions: List[DocumentTextVersion]
    chunks: List[VersionedChunk]
    source_records: Dict[str, Dict[str, Any]]
    duplicates: Dict[str, Any] = field(default_factory=dict)
    hosts_used: List[Dict[str, Any]] = field(default_factory=list)
    discovery_host_note: str = ""
    reader_version: str = CORPUS_READER_VERSION
    integrity: Dict[str, Any] = field(default_factory=dict)
    loaded_at: str = ""

    # -- indexing view ----------------------------------------------------------

    @property
    def version_by_doc(self) -> Dict[str, DocumentTextVersion]:
        return {version.doc_id: version for version in self.text_versions}

    def _has_text(self, document: SourceDocument) -> bool:
        version = self.version_by_doc.get(document.doc_id)
        return bool(version is not None and version.normalized_text.strip())

    @property
    def indexed_documents(self) -> List[SourceDocument]:
        """Documents that carry real text — the only ones the index may contain."""
        return [document for document in self.documents if self._has_text(document)]

    @property
    def absent_documents(self) -> List[SourceDocument]:
        """Documents with no text version (acquisition failed or metadata only)."""
        return [document for document in self.documents if not self._has_text(document)]

    @property
    def current_text_versions(self) -> List[DocumentTextVersion]:
        by_doc = self.version_by_doc
        return [
            by_doc[document.doc_id]
            for document in self.indexed_documents
            if by_doc[document.doc_id].is_current
        ]

    @property
    def chunks_by_doc(self) -> Dict[str, List[VersionedChunk]]:
        grouped: Dict[str, List[VersionedChunk]] = {}
        for chunk in self.chunks:
            grouped.setdefault(chunk.doc_id, []).append(chunk)
        return grouped

    # -- provenance view --------------------------------------------------------

    def source_record(self, source_scope_id: str) -> Dict[str, Any]:
        return self.source_records.get(source_scope_id, {})

    def document_authority(self, doc_id: str) -> Dict[str, Any]:
        """Per-document authority classification recorded by the acquisition run."""
        for document in self.documents:
            if document.doc_id == doc_id:
                return dict(
                    self.source_record(document.source_scope_id).get("document_authority") or {}
                )
        return {}

    def absent_sources(self) -> List[Dict[str, Any]]:
        """The sources that contributed zero documents/chunks, with their codes."""
        records: List[Dict[str, Any]] = []
        for document in self.absent_documents:
            record = self.source_record(document.source_scope_id)
            records.append(
                {
                    "source_scope_id": document.source_scope_id,
                    "doc_id": document.doc_id,
                    "case_id": record.get("case_id", UNKNOWN),
                    "status": document.access_status,
                    "failure_code": record.get("failure_code"),
                    "reason": document.not_retrieved_reason,
                    "authority_classification": (
                        record.get("document_authority") or {}
                    ).get("classification", UNKNOWN),
                    "ingest_status": document.ingest_status,
                    "chunks_indexed": 0,
                    "documents_indexed": 0,
                }
            )
        return records

    def authority_classification_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for document in self.documents:
            classification = self.document_authority(document.doc_id).get(
                "classification", UNKNOWN
            )
            counts[classification] = counts.get(classification, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reader_version": self.reader_version,
            "corpus_dir": self.corpus_dir,
            "corpus_version": self.corpus_version,
            "frozen_corpus_version": self.frozen_corpus_version,
            "manifest_version": self.manifest_version,
            "acquisition_version": self.acquisition_version,
            "normalizer_version": self.normalizer_version,
            "chunker_version": self.chunker_version,
            "index_version": self.index_version,
            "generated_at": self.generated_at,
            "loaded_at": self.loaded_at,
            "manifest_counts": dict(self.manifest_counts),
            "documents_on_disk": len(self.documents),
            "documents_indexed": len(self.indexed_documents),
            "documents_absent": len(self.absent_documents),
            "text_versions": len(self.text_versions),
            "chunks_indexed": len(self.chunks),
            "authority_classification_counts": self.authority_classification_counts(),
            "absent_sources": self.absent_sources(),
            "duplicates": dict(self.duplicates),
            "hosts_used": list(self.hosts_used),
            "discovery_host_note": self.discovery_host_note,
            "integrity": dict(self.integrity),
        }


def _chunk_file_path(corpus_dir: Path, case_id: str, source_scope_id: str) -> Path:
    return corpus_dir / CHUNKS_DIRNAME / case_id / f"{source_scope_id}.chunks.json"


def load_corpus(corpus_dir: str | Path = DEFAULT_CORPUS_DIR) -> CorpusSnapshot:
    """Read one acquired corpus directory into a :class:`CorpusSnapshot`.

    Raises
    ------
    FileNotFoundError
        When a required artefact is missing.
    CorpusIntegrityError
        When the artefacts disagree with each other or with their own hashes.
    """
    base = Path(corpus_dir)
    if not base.is_absolute():
        base = REPO_ROOT / base
    if not base.is_dir():
        raise FileNotFoundError(f"语料目录不存在: {base}")

    manifest = _load_json(base / MANIFEST_FILE)
    if not isinstance(manifest, dict) or "sources" not in manifest:
        raise CorpusIntegrityError(f"{base / MANIFEST_FILE}: 缺少 sources 清单")
    corpus_version = str(manifest.get("corpus_version") or "")
    if not corpus_version:
        raise CorpusIntegrityError(f"{base / MANIFEST_FILE}: 缺少 corpus_version")

    documents = [
        _record_from_dict(SourceDocument, payload, f"{DOCUMENTS_FILE}[{index}]")
        for index, payload in enumerate(_load_json(base / DOCUMENTS_FILE))
    ]
    text_versions = [
        _record_from_dict(DocumentTextVersion, payload, f"{TEXT_VERSIONS_FILE}[{index}]")
        for index, payload in enumerate(_load_json(base / TEXT_VERSIONS_FILE))
    ]

    source_records: Dict[str, Dict[str, Any]] = {}
    for entry in manifest["sources"]:
        source_records[str(entry["source_scope_id"])] = entry

    checks: List[str] = ["manifest_document_count", "version_text_sha256", "version_char_length"]

    # -- manifest <-> documents/versions agreement -----------------------------
    counts = manifest.get("counts") or {}
    if counts.get("total") != len(documents):
        raise CorpusIntegrityError(
            f"manifest counts.total={counts.get('total')} != documents.json 条目数 {len(documents)}"
        )
    full_text_docs = [d for d in documents if d.ingest_status == INGEST_FULL_TEXT]
    metadata_only_docs = [d for d in documents if d.ingest_status == INGEST_METADATA_ONLY]
    if len(full_text_docs) + len(metadata_only_docs) != len(documents):
        unexpected = sorted(
            {d.ingest_status for d in documents} - {INGEST_FULL_TEXT, INGEST_METADATA_ONLY}
        )
        raise CorpusIntegrityError(f"documents.json 出现未知 ingest_status: {unexpected}")
    if counts.get("acquired") != len(full_text_docs):
        raise CorpusIntegrityError(
            f"manifest counts.acquired={counts.get('acquired')} != ingest_status=full_text 文档数 "
            f"{len(full_text_docs)}"
        )
    if counts.get("failed") != len(metadata_only_docs):
        raise CorpusIntegrityError(
            f"manifest counts.failed={counts.get('failed')} != ingest_status=metadata_only 文档数 "
            f"{len(metadata_only_docs)}"
        )
    if len(text_versions) != len(full_text_docs):
        raise CorpusIntegrityError(
            f"text_versions.json 条目数 {len(text_versions)} != ingest_status=full_text 文档数 "
            f"{len(full_text_docs)}"
        )
    doc_by_id = {document.doc_id: document for document in documents}
    if len(doc_by_id) != len(documents):
        raise CorpusIntegrityError("documents.json 存在重复 doc_id")
    for document in documents:
        record = source_records.get(document.source_scope_id)
        if record is None:
            raise CorpusIntegrityError(
                f"{document.doc_id}: source_scope_id {document.source_scope_id} 不在 manifest.sources 中"
            )
        if document.ingest_status == INGEST_FULL_TEXT and record.get("status") != STATUS_ACQUIRED:
            raise CorpusIntegrityError(
                f"{document.doc_id}: ingest_status=full_text 但 manifest status={record.get('status')!r}"
            )
        if document.ingest_status == INGEST_METADATA_ONLY and record.get("status") == STATUS_ACQUIRED:
            raise CorpusIntegrityError(
                f"{document.doc_id}: manifest status=ACQUIRED 但 ingest_status=metadata_only"
            )
        if not (record.get("document_authority") or {}).get("classification"):
            raise CorpusIntegrityError(
                f"{document.source_scope_id}: manifest 缺少 document_authority.classification"
            )

    # -- text version self-verification ----------------------------------------
    for version in text_versions:
        if version.doc_id not in doc_by_id:
            raise CorpusIntegrityError(f"{version.text_version_id}: doc_id 不在 documents.json 中")
        if version.text_sha256 != sha256_text(version.normalized_text):
            raise CorpusIntegrityError(
                f"{version.text_version_id}: text_sha256 与 normalized_text 不一致"
            )
        if version.char_length != len(version.normalized_text):
            raise CorpusIntegrityError(
                f"{version.text_version_id}: char_length={version.char_length} != "
                f"len(normalized_text)={len(version.normalized_text)}"
            )

    # -- chunks: one file per acquired source, spans re-verified ----------------
    checks.extend(["chunk_span_slice", "chunk_sha256", "chunk_leakage_guard", "chunk_manifest_count"])
    version_by_doc = {version.doc_id: version for version in text_versions}
    chunks: List[VersionedChunk] = []
    chunk_file_count = 0
    span_checks = 0
    for document in documents:
        case_id = str(source_records[document.source_scope_id].get("case_id") or "")
        path = _chunk_file_path(base, case_id, document.source_scope_id)
        acquired = document.ingest_status == INGEST_FULL_TEXT
        if not acquired:
            if path.exists():
                raise CorpusIntegrityError(
                    f"{path}: 未获取来源 {document.source_scope_id} 不应存在分块文件"
                )
            continue
        if not path.exists():
            raise CorpusIntegrityError(f"{path}: 已获取来源 {document.source_scope_id} 缺少分块文件")
        chunk_file_count += 1
        payload = _load_json(path)
        origin = str(path.relative_to(base)).replace("\\", "/")
        if payload.get("corpus_version") != corpus_version:
            raise CorpusIntegrityError(
                f"{origin}: corpus_version={payload.get('corpus_version')!r} != {corpus_version!r}"
            )
        if payload.get("doc_id") != document.doc_id:
            raise CorpusIntegrityError(f"{origin}: doc_id 与文档记录不一致")
        if payload.get("source_scope_id") != document.source_scope_id:
            raise CorpusIntegrityError(f"{origin}: source_scope_id 与文档记录不一致")
        version = version_by_doc.get(document.doc_id)
        if version is None:
            raise CorpusIntegrityError(f"{origin}: 缺少对应 text_version")
        if payload.get("text_version_id") != version.text_version_id:
            raise CorpusIntegrityError(f"{origin}: text_version_id 与文本版本记录不一致")
        file_chunks = [
            _record_from_dict(VersionedChunk, item, f"{origin}#{index}")
            for index, item in enumerate(payload.get("chunks") or [])
        ]
        file_chunker = str(payload.get("chunker_version") or "")
        if file_chunker and any(chunk.chunker_version != file_chunker for chunk in file_chunks):
            raise CorpusIntegrityError(
                f"{origin}: file chunker_version={file_chunker!r} 与 chunk record 不一致"
            )
        expected = (source_records[document.source_scope_id].get("chunks") or {}).get("count")
        if expected != len(file_chunks):
            raise CorpusIntegrityError(
                f"{origin}: manifest 记录 {expected} 个分块，文件含 {len(file_chunks)} 个"
            )
        for chunk in file_chunks:
            if chunk.doc_id != document.doc_id or chunk.text_version_id != version.text_version_id:
                raise CorpusIntegrityError(f"{chunk.chunk_id}: 文档/文本版本归属不一致")
            if chunk.corpus_version != corpus_version:
                raise CorpusIntegrityError(
                    f"{chunk.chunk_id}: corpus_version={chunk.corpus_version!r} != {corpus_version!r}"
                )
            if version.normalized_text[chunk.span_start : chunk.span_end] != chunk.chunk_text:
                raise CorpusIntegrityError(
                    f"{chunk.chunk_id}: span [{chunk.span_start}, {chunk.span_end}) 无法还原 chunk_text"
                )
            if chunk.chunk_sha256 != sha256_text(chunk.chunk_text):
                raise CorpusIntegrityError(f"{chunk.chunk_id}: chunk_sha256 与 chunk_text 不一致")
            if chunk.char_count != len(chunk.chunk_text):
                raise CorpusIntegrityError(f"{chunk.chunk_id}: char_count 与 chunk_text 长度不一致")
            span_checks += 1
        chunks.extend(file_chunks)

    chunk_versions = {str(chunk.chunker_version) for chunk in chunks if chunk.chunker_version}
    if len(chunk_versions) > 1:
        raise CorpusIntegrityError(
            f"{base}: 多个 chunker_version {sorted(chunk_versions)}；必须单一版本"
        )
    manifest_chunker = str(manifest.get("chunker_version") or "")
    if manifest_chunker and chunk_versions and manifest_chunker not in chunk_versions:
        raise CorpusIntegrityError(
            f"{base / MANIFEST_FILE}: manifest chunker_version={manifest_chunker!r} "
            f"与 chunk record {sorted(chunk_versions)} 不一致"
        )
    derived_chunker_version = next(iter(chunk_versions), "") or manifest_chunker

    snapshot = CorpusSnapshot(
        corpus_dir=str(base).replace("\\", "/"),
        corpus_version=corpus_version,
        frozen_corpus_version=str(manifest.get("frozen_corpus_version") or ""),
        manifest_version=str(manifest.get("manifest_version") or ""),
        acquisition_version=str(manifest.get("acquisition_version") or ""),
        normalizer_version=str(manifest.get("normalizer_version") or ""),
        chunker_version=derived_chunker_version,
        index_version=str(manifest.get("index_version") or ""),
        generated_at=str(manifest.get("generated_at") or ""),
        manifest_counts=dict(counts),
        documents=documents,
        text_versions=text_versions,
        chunks=chunks,
        source_records=source_records,
        duplicates=dict(manifest.get("duplicates") or {}),
        hosts_used=list(manifest.get("hosts_used") or []),
        discovery_host_note=str(manifest.get("discovery_host_note") or ""),
        loaded_at=now_iso(),
    )
    snapshot.integrity = {
        "checks": checks,
        "chunk_files_read": chunk_file_count,
        "chunks_span_verified": span_checks,
        "documents_on_disk": len(documents),
        "documents_indexed": len(snapshot.indexed_documents),
        "documents_absent": len(snapshot.absent_documents),
        "text_versions_verified": len(text_versions),
        "manifest_counts": dict(counts),
        "note": (
            "读取即校验：清单计数、text_sha256、char_length、每个分块的 span 还原与 chunk_sha256 "
            "全部核对通过才返回；任一不一致即抛 CorpusIntegrityError，绝不修补、绝不回填。"
        ),
    }
    return snapshot


__all__ = [
    "CORPUS_READER_VERSION",
    "DEFAULT_CORPUS_DIR",
    "CorpusIntegrityError",
    "CorpusSnapshot",
    "load_corpus",
]
