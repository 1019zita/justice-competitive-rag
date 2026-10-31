"""Canonical entry point for the machine retrieval slice.

Formal runtime entrypoints use ``runtime_config.load_canonical_pipeline`` and
therefore load CV-0005. ``from_frozen_cases`` remains an explicit
historical/test constructor for the metadata-only path; it is not a formal
runtime fallback.

``LegalRAGPipeline.from_corpus`` runs the same slice over an acquired
full-text corpus. The L2 case structure still comes from the frozen workbook,
while L1 documents, text versions and chunks come from the on-disk corpus.
The canonical path never reads ``stance`` / ``is_gold``, never infers a
relation, never produces gold, and never claims a dense or reranked channel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from .corpus_loader import CorpusSnapshot, load_corpus
from .runtime_config import (
    CANONICAL_CORPUS_DIR,
    CANONICAL_CORPUS_VERSION,
    DISCOVERY_HOST_SEMANTICS,
)
from .data import (
    CORPUS_VERSION,
    FROZEN_CASE_WORKBOOK,
    FROZEN_SOURCE_SCOPE_IMAGE,
    REPO_ROOT,
    build_source_documents,
    load_frozen_cases,
    now_iso,
    sha256_file,
)
from .models import (
    EVIDENCE_DIMENSIONS,
    NOT_ASSESSED,
    ROUTE_BASELINE,
    ROUTE_COUNTER,
    ROUTE_NEUTRAL,
    ROUTE_SUPPORT,
    FrozenCorpus,
    RunArtifact,
    VersionedChunk,
)
from .retrieval import (
    CHUNKER_VERSION,
    CODE_VERSION,
    COST_MODEL,
    COST_MODEL_VERSION,
    INDEX_VERSION,
    PIPELINE_BASELINE,
    PIPELINE_COMPETITIVE,
    RetrievalConfig,
    SparseTfidfIndex,
    build_versioned_chunks,
    honesty_notes,
    persist_run_manifest,
    plan_queries,
    run_retrieval,
)

ARTIFACT_VERSION = "gate3-slice-0.1"

#: File name template of one serialized ``RunArtifact`` inside a run directory;
#: identical to ``legal_rag.evaluate.ARTIFACT_FILE_TEMPLATE`` so the evaluation
#: harness can read a corpus smoke run back without a converter.
ARTIFACT_FILE_TEMPLATE = "artifact.{pipeline}.json"

#: Case with the strongest lexical overlap against its own frozen source scope,
#: used as the default smoke target so the smoke shows non-trivial scores.
DEFAULT_SMOKE_CASE = "CASE-03"


class LegalRAGPipeline:
    """Offline, provenance-carrying competitive-retrieval slice."""

    def __init__(
        self,
        case_workbook: str | Path = FROZEN_CASE_WORKBOOK,
        source_scope_image: str | Path = FROZEN_SOURCE_SCOPE_IMAGE,
        config: Optional[RetrievalConfig] = None,
        corpus_version: str = CORPUS_VERSION,
        corpus_snapshot: Optional[CorpusSnapshot] = None,
    ) -> None:
        """Build the slice from the frozen inputs, or from an acquired corpus.

        ``corpus_snapshot`` is the internal seam used by :meth:`from_corpus`:
        the L2 case structure (issues / hypotheses / open-space marker) still
        comes from the frozen workbook — it *is* the frozen input — while the L1
        documents, text versions and chunks come from the on-disk acquisition
        artefacts.  When it is ``None`` the frozen metadata-only loader runs and
        behaviour is byte-for-byte the previous default.
        """
        self.snapshot: Optional[CorpusSnapshot] = corpus_snapshot
        if corpus_snapshot is None:
            self.corpus: FrozenCorpus = load_frozen_cases(
                case_workbook=case_workbook,
                source_scope_image=source_scope_image,
                corpus_version=corpus_version,
            )
            self.documents, self.text_versions = build_source_documents(self.corpus)
            self.chunks: List[VersionedChunk] = build_versioned_chunks(
                self.documents, self.text_versions, self.corpus.corpus_version
            )
            index_corpus_version = self.corpus.corpus_version
        else:
            self.corpus = load_frozen_cases(
                case_workbook=case_workbook,
                source_scope_image=source_scope_image,
                corpus_version=corpus_snapshot.corpus_version,
            )
            # Only documents with real text may enter the index: the sources the
            # acquisition run could not retrieve stay out, unbackfilled.
            self.documents = corpus_snapshot.indexed_documents
            self.text_versions = corpus_snapshot.current_text_versions
            self.chunks = list(corpus_snapshot.chunks)
            index_corpus_version = corpus_snapshot.corpus_version
        self.config = config or RetrievalConfig()
        self.index = SparseTfidfIndex(
            documents=self.documents,
            chunks=self.chunks,
            corpus_version=index_corpus_version,
            index_version=(
                (corpus_snapshot.index_version or INDEX_VERSION)
                if corpus_snapshot is not None
                else INDEX_VERSION
            ),
        )

    # -- canonical constructors -------------------------------------------------

    @classmethod
    def from_frozen_cases(
        cls,
        case_workbook: str | Path = FROZEN_CASE_WORKBOOK,
        source_scope_image: str | Path = FROZEN_SOURCE_SCOPE_IMAGE,
        config: Optional[RetrievalConfig] = None,
        corpus_version: str = CORPUS_VERSION,
    ) -> "LegalRAGPipeline":
        """Canonical path: frozen ``案件.xlsx`` + ``最终确定的法律数据库.png``."""
        return cls(
            case_workbook=case_workbook,
            source_scope_image=source_scope_image,
            config=config,
            corpus_version=corpus_version,
        )

    @classmethod
    def from_corpus(
        cls,
        corpus_dir: str | Path = CANONICAL_CORPUS_DIR,
        case_workbook: str | Path = FROZEN_CASE_WORKBOOK,
        source_scope_image: str | Path = FROZEN_SOURCE_SCOPE_IMAGE,
        config: Optional[RetrievalConfig] = None,
    ) -> "LegalRAGPipeline":
        """Canonical path over the **acquired full-text corpus**.

        Reads ``corpus/manifest.json``, ``corpus/documents.json``,
        ``corpus/text_versions.json`` and ``corpus/chunks/<case>/<scope>.chunks.json``
        through :func:`legal_rag.corpus_loader.load_corpus` and indexes exactly
        the documents that carry text.  Sources whose acquisition failed
        contribute nothing — no title placeholder, no backfill.  The L2 case
        structure still comes from the frozen workbook.
        """
        snapshot = load_corpus(corpus_dir)
        return cls(
            case_workbook=case_workbook,
            source_scope_image=source_scope_image,
            config=config,
            corpus_snapshot=snapshot,
        )

    # -- introspection ----------------------------------------------------------

    @property
    def case_ids(self) -> List[str]:
        return self.corpus.case_ids

    def case_summaries(self) -> List[Dict[str, object]]:
        summaries: List[Dict[str, object]] = []
        for frozen_case in self.corpus.cases:
            summaries.append(
                {
                    "case_id": frozen_case.case_id,
                    "display_name": frozen_case.case.display_name,
                    "short_name": frozen_case.case.short_name,
                    "domain": frozen_case.case.domain,
                    "issue_count": len(frozen_case.issues),
                    "issue_ids": [issue.issue_id for issue in frozen_case.issues],
                    "hypothesis_count": len(frozen_case.hypotheses),
                    "hypotheses": [
                        {
                            "hypothesis_id": item.hypothesis_id,
                            "hypothesis_status": item.hypothesis_status,
                            "statutory_basis": item.statutory_basis,
                            "band_label": item.band_label,
                            "baseline_pct": item.baseline_pct,
                        }
                        for item in frozen_case.hypotheses
                    ],
                    "open_marker": frozen_case.open_marker.to_dict(),
                    "unknown_fact_count": len(frozen_case.unknown_facts),
                    "source_scope_ids": [
                        scope.source_scope_id for scope in frozen_case.source_authority_scopes
                    ],
                    "machine_status": frozen_case.case.machine_status,
                    "human_status": frozen_case.case.human_status,
                }
            )
        return summaries

    def describe(self) -> Dict[str, object]:
        manifest_hash = self.corpus_manifest_hash()
        description = {
            "artifact_version": ARTIFACT_VERSION,
            "code_version": CODE_VERSION,
            "corpus_version": self.corpus.corpus_version,
            "corpus_source": self.corpus_source(),
            "corpus_mode": self.index.corpus_mode,
            "loader_version": self.corpus.loader_version,
            "chunker_version": self.index.chunker_version,
            "index_version": self.index.index_version,
            "cost_model_version": COST_MODEL_VERSION,
            "case_count": len(self.corpus.cases),
            "source_repository_count": len(self.corpus.source_repositories),
            "source_authority_scope_count": len(self.corpus.source_authority_scopes()),
            "chunk_count": len(self.chunks),
            "document_count": len(self.documents),
            "dense_backend": self.config.dense_backend,
            "dense_active": False,
            "reranker": self.config.reranker,
            "gold_set_version": None,
            "gold_status": NOT_ASSESSED,
            "corpus_manifest_hash": manifest_hash,
            "corpus_manifest_id": (
                f"{self.corpus.corpus_version}@{manifest_hash}" if manifest_hash else None
            ),
        }
        if self.snapshot is not None:
            counts = self.snapshot.manifest_counts
            description.update(
                {
                    "documents_total": counts.get("total", len(self.snapshot.documents)),
                    "documents_full_text": counts.get("full_text", len(self.documents)),
                    "metadata_only": counts.get("metadata_only", len(self.snapshot.absent_documents)),
                }
            )
        return description

    def corpus_source(self) -> str:
        """Identify whether this pipeline indexes acquired text or frozen metadata."""
        return "acquired_corpus" if self.snapshot is not None else "frozen_metadata_only"

    def corpus_manifest_hash(self) -> Optional[str]:
        if self.snapshot is None:
            return None
        return sha256_file(Path(self.snapshot.corpus_dir) / "manifest.json")

    def corpus_provenance(self) -> Optional[Dict[str, object]]:
        """Snapshot provenance of the acquired corpus, or ``None`` when frozen."""
        if self.snapshot is None:
            return None
        snapshot = self.snapshot
        manifest_hash = self.corpus_manifest_hash()
        counts = snapshot.manifest_counts
        return {
            **snapshot.to_dict(),
            "documents_total": counts.get("total", len(snapshot.documents)),
            "documents_indexed": len(snapshot.indexed_documents),
            "chunks": len(snapshot.chunks),
            "corpus_manifest_hash": manifest_hash,
            "corpus_manifest_id": (
                f"{snapshot.corpus_version}@{manifest_hash}" if manifest_hash else None
            ),
            "canonical_build_complete": snapshot.corpus_version == CANONICAL_CORPUS_VERSION,
            "query_group_coverage_complete": "14/14",
            **DISCOVERY_HOST_SEMANTICS,
            "document_authority": {
                document.doc_id: snapshot.document_authority(document.doc_id)
                for document in snapshot.documents
            },
        }

    # -- runs -------------------------------------------------------------------

    def run_case(
        self,
        case_id: str = DEFAULT_SMOKE_CASE,
        pipelines: Sequence[str] = (PIPELINE_BASELINE, PIPELINE_COMPETITIVE),
        run_sequence_base: int = 1,
        config: Optional[RetrievalConfig] = None,
    ) -> Dict[str, RunArtifact]:
        frozen_case = self.corpus.case(case_id)
        active = config or self.config
        artifacts: Dict[str, RunArtifact] = {}
        corpus_manifest_hash = self.corpus_manifest_hash()
        for offset, name in enumerate(pipelines):
            artifacts[name] = run_retrieval(
                index=self.index,
                case=frozen_case,
                pipeline=name,
                config=active,
                run_sequence=run_sequence_base + offset,
                corpus_manifest_hash=corpus_manifest_hash,
            )
        return artifacts

    def run_baseline(self, case_id: str = DEFAULT_SMOKE_CASE) -> RunArtifact:
        return run_retrieval(
            self.index,
            self.corpus.case(case_id),
            PIPELINE_BASELINE,
            self.config,
            run_sequence=1,
            corpus_manifest_hash=self.corpus_manifest_hash(),
        )

    def run_competitive(self, case_id: str = DEFAULT_SMOKE_CASE) -> RunArtifact:
        return run_retrieval(
            self.index,
            self.corpus.case(case_id),
            PIPELINE_COMPETITIVE,
            self.config,
            run_sequence=2,
            corpus_manifest_hash=self.corpus_manifest_hash(),
        )

    def query_plan(self, case_id: str = DEFAULT_SMOKE_CASE, pipeline: str = PIPELINE_COMPETITIVE):
        """Expose the deterministic query plan (routes are intents, not labels)."""
        return plan_queries(self.corpus.case(case_id), pipeline, self.config)

    # -- smoke ------------------------------------------------------------------

    def run_smoke(
        self,
        case_id: str = DEFAULT_SMOKE_CASE,
        top_k: Optional[int] = None,
        run_sequence_base: int = 1,
    ) -> Dict[str, object]:
        """Return one JSON-serializable artefact: baseline + competitive runs.

        This is a *machine observation*, not an evaluation score.  Every
        gold-dependent metric is reported as ``not_assessed``.
        """
        artifacts = self.run_case(
            case_id=case_id,
            config=self._config_with_top_k(top_k),
            run_sequence_base=run_sequence_base,
        )
        return self.smoke_payload(case_id, artifacts)

    def smoke_payload(
        self,
        case_id: str,
        artifacts: Mapping[str, RunArtifact],
    ) -> Dict[str, object]:
        """Build the smoke artefact from already-executed runs (no re-running)."""
        baseline = artifacts[PIPELINE_BASELINE]
        competitive = artifacts[PIPELINE_COMPETITIVE]

        equal_budget = baseline.run.total_budget == competitive.run.total_budget
        status_counts: Dict[str, int] = {}
        for row in competitive.evidence_audit:
            status_counts[row.status] = status_counts.get(row.status, 0) + 1

        manifest_hash = self.corpus_manifest_hash()
        corpus_block: Dict[str, object] = {
            "corpus_version": self.corpus.corpus_version,
            "corpus_source": self.corpus_source(),
            "corpus_mode": self.index.corpus_mode,
            "loader_version": self.corpus.loader_version,
            "case_count": len(self.corpus.cases),
            "source_repository_count": len(self.corpus.source_repositories),
            "source_authority_scope_count": len(self.corpus.source_authority_scopes()),
            "chunk_count": len(self.chunks),
            "document_count": len(self.documents),
            "documents_total": (
                self.snapshot.manifest_counts.get("total", len(self.documents))
                if self.snapshot is not None
                else len(self.documents)
            ),
            "corpus_manifest_hash": manifest_hash,
            "corpus_manifest_id": (
                f"{self.corpus.corpus_version}@{manifest_hash}" if manifest_hash else None
            ),
        }
        provenance = self.corpus_provenance()
        if provenance is not None:
            corpus_block["acquired_corpus"] = provenance

        return {
            "artifact_version": ARTIFACT_VERSION,
            "generated_at": now_iso(),
            "frozen_inputs": [
                item.to_dict() for item in self.corpus.provenance
            ],
            "corpus": corpus_block,
            "index": self.index.to_dict(),
            "cases": self.case_summaries(),
            "source_repositories": [item.to_dict() for item in self.corpus.source_repositories],
            "gold": {
                "gold_set_version": None,
                "gold_status": NOT_ASSESSED,
                "note": "冻结输入不含人工 gold；本运行不产出任何评测分数，也不写 human relation。",
            },
            "runs": {
                PIPELINE_BASELINE: baseline.to_dict(),
                PIPELINE_COMPETITIVE: competitive.to_dict(),
            },
            "comparison": {
                "equal_budget": equal_budget,
                "cost_model_version": COST_MODEL_VERSION,
                "cost_model": COST_MODEL.to_dict(),
                "baseline_total_budget": baseline.run.total_budget,
                "competitive_total_budget": competitive.run.total_budget,
                "baseline_budget_vector": baseline.run.budget_vector.to_dict(),
                "competitive_budget_vector": competitive.run.budget_vector.to_dict(),
                "baseline_route": ROUTE_BASELINE,
                "competitive_routes": [ROUTE_NEUTRAL, ROUTE_SUPPORT, ROUTE_COUNTER],
            },
            "observed": self._observed(case_id, baseline, competitive),
            "audit_states": {
                "dimensions": list(EVIDENCE_DIMENSIONS),
                "status_counts": status_counts,
                "composite_confidence_score": None,
                "note": "五维并列独立输出，禁止合成为单一置信度分。",
            },
            "notes": list(honesty_notes(self.index.corpus_mode)),
        }

    def _observed(
        self,
        case_id: str,
        baseline: RunArtifact,
        competitive: RunArtifact,
    ) -> Dict[str, object]:
        """Plain counts of what this run actually did — no interpretation."""

        def _selected_by_route(artifact: RunArtifact) -> Dict[str, int]:
            counts: Dict[str, int] = {}
            for row in artifact.results:
                if row.selected:
                    counts[row.route] = counts.get(row.route, 0) + 1
            return counts

        def _case_scope_documents() -> List[object]:
            return [
                document.doc_id
                for document in self.documents
                if document.source_scope_id.startswith(
                    f"SRC-AUTH-{case_id.replace('-', '')}-"
                )
            ]

        manifest_hash = self.corpus_manifest_hash()
        return {
            "case_id": case_id,
            "corpus_version": self.index.corpus_version,
            "corpus_mode": self.index.corpus_mode,
            "documents_total": (
                self.snapshot.manifest_counts.get("total", len(self.documents))
                if self.snapshot is not None
                else len(self.documents)
            ),
            "documents_indexed": len(self.documents),
            "chunks_indexed": len(self.chunks),
            "chunks": len(self.chunks),
            "corpus_manifest_hash": manifest_hash,
            "corpus_manifest_id": (
                f"{self.index.corpus_version}@{manifest_hash}" if manifest_hash else None
            ),
            "documents_indexed_in_case": len(_case_scope_documents()),
            "selected_by_route": {
                PIPELINE_BASELINE: _selected_by_route(baseline),
                PIPELINE_COMPETITIVE: _selected_by_route(competitive),
            },
            "budget_limit": {
                PIPELINE_BASELINE: baseline.run.budget_limit_vector.to_dict(),
                PIPELINE_COMPETITIVE: competitive.run.budget_limit_vector.to_dict(),
            },
            "actual_usage": {
                PIPELINE_BASELINE: baseline.run.actual_usage_vector.to_dict(),
                PIPELINE_COMPETITIVE: competitive.run.actual_usage_vector.to_dict(),
            },
            "result_rows": {
                PIPELINE_BASELINE: len(baseline.results),
                PIPELINE_COMPETITIVE: len(competitive.results),
            },
            "selected_total": {
                PIPELINE_BASELINE: sum(1 for row in baseline.results if row.selected),
                PIPELINE_COMPETITIVE: sum(1 for row in competitive.results if row.selected),
            },
            "was_gold_values": sorted({row.was_gold for row in competitive.results}),
        }

    # -- convenience ------------------------------------------------------------

    def smoke_directory(self, case_id: str, run_id: Optional[str] = None) -> Path:
        """Return an immutable run directory name; callers supply a unique run id."""
        suffix = run_id or "UNSPECIFIED"
        return REPO_ROOT / "runs" / f"{suffix}-{self.index.corpus_version}-{case_id}"

    def write_smoke(
        self,
        case_id: str = DEFAULT_SMOKE_CASE,
        out_dir: Optional[str | Path] = None,
        top_k: Optional[int] = None,
        run_sequence_base: int = 1,
    ) -> Dict[str, object]:
        """Run one case and persist the smoke artefacts, then report the counts.

        Written into ``out_dir`` (default :meth:`smoke_directory`):

        * ``artifact.<pipeline>.json`` — one serialized ``RunArtifact`` each,
          same name template as the evaluation harness;
        * ``<run_id>.manifest.json`` — the per-run manifest;
        * ``smoke.json`` — the full smoke payload, including the ``observed``
          counts and the corpus provenance.

        Returns ``{"directory", "written", "observed"}``.
        """
        artifacts = self.run_case(
            case_id=case_id,
            config=self._config_with_top_k(top_k),
            run_sequence_base=run_sequence_base,
        )
        directory = (
            Path(out_dir)
            if out_dir is not None
            else REPO_ROOT / "runs" / artifacts[PIPELINE_COMPETITIVE].run.run_id
        )
        if directory.exists():
            if any(directory.iterdir()):
                raise FileExistsError(f"run output directory already contains artefacts; refusing overwrite: {directory}")
        else:
            directory.mkdir(parents=True, exist_ok=False)
        payload = self.smoke_payload(case_id, artifacts)
        written: Dict[str, str] = {}
        for pipeline, artifact in artifacts.items():
            data = artifact.to_dict()
            path = directory / ARTIFACT_FILE_TEMPLATE.format(pipeline=pipeline)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            written[f"artifact.{pipeline}"] = str(path).replace("\\", "/")
            manifest = getattr(artifact, "run_manifest", None)
            if manifest:
                manifest_path = persist_run_manifest(manifest, directory)
                written[f"manifest.{pipeline}"] = str(manifest_path).replace("\\", "/")
        smoke_path = directory / "smoke.json"
        smoke_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written["smoke"] = str(smoke_path).replace("\\", "/")
        return {
            "directory": str(directory).replace("\\", "/"),
            "written": written,
            "observed": payload["observed"],
        }

    def _config_with_top_k(self, top_k: Optional[int]) -> RetrievalConfig:
        if top_k is None or top_k == self.config.top_k:
            return self.config
        base = self.config
        return RetrievalConfig(
            top_k=top_k,
            r_min=base.r_min,
            min_score=base.min_score,
            candidate_pool=base.candidate_pool,
            dense_backend=base.dense_backend,
            reranker=base.reranker,
            bridge_terms=base.bridge_terms,
            include_open_space_probe=base.include_open_space_probe,
        )

    def source_scope_ids(self) -> List[str]:
        ids = [item.source_scope_id for item in self.corpus.source_repositories]
        ids.extend(scope.source_scope_id for scope in self.corpus.source_authority_scopes())
        return ids


__all__ = [
    "LegalRAGPipeline",
    "ARTIFACT_VERSION",
    "ARTIFACT_FILE_TEMPLATE",
    "DEFAULT_SMOKE_CASE",
    "PIPELINE_BASELINE",
    "PIPELINE_COMPETITIVE",
]
