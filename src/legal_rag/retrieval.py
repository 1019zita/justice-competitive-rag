"""Offline competitive-retrieval slice over the frozen inputs.

What this module does
---------------------
* Builds versioned legal chunks with stable ids, spans and provenance, and with
  ``leakage_guard_ok`` verified (no gold label ever enters ``embedding_text``).
* Runs a **single-query baseline** (``route=baseline_single``) per
  ``(case, issue, hypothesis)`` triple, and a **competitive** run that issues
  three *intent* routes (``neutral_governing`` / ``support`` /
  ``counter_weakening``) per triple.
* Records durable query traces, per-result provenance, omission reasons, a
  **pre-registered fixed budget cap** (``budget_limit_vector``, identical across
  the paired pipelines) kept separate from the observed ``actual_usage_vector``,
  and a fixed cost-model version, so baseline and competitive are equal-budget
  comparable.
* Writes a run manifest carrying every member required by ``DATA_SCHEMA.md``
  §6.5A and ``EVALUATION_PROTOCOL.md`` §10 (dependency versions, workspace
  state, random seed, corpus/index/query-set/gold versions, cost-model version,
  budget cap) together with a hash over all of them.
* Attaches five **independent** evidence-audit dimensions.  Nothing is fused
  into a single confidence score, and no evaluation score is produced.

Honest limitations (kept in the artefacts, not only in prose)
-------------------------------------------------------------
* Only sparse character TF-IDF is active.  ``score_dense`` stays ``NULL`` and
  the run never claims a hybrid/dense channel.  The dense backend is optional
  and unverified.
* ``authority_multiplier`` is ``NULL``: the authority-tier multiplier ``μ(d)``
  is explicitly not preset by the design.
* ``bridge_terms`` is empty: the human-verified bridge-term list does not exist
  yet, and inventing one is forbidden.
* The frozen corpus is ``metadata_only`` (authority titles, no official full
  text), so lexical scores are weak by construction and must not be read as
  legal relevance.  An index built from the *acquired* corpus
  (``legal_rag.corpus_loader``) carries real full text instead; its mode is
  derived from the indexed documents themselves (:func:`corpus_mode_of`) and its
  artefacts carry :data:`CORPUS_HONESTY_NOTES` rather than the frozen notes.
* Routes are retrieval *intents*, never labels for the returned documents, and
  relations are never inferred.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
import subprocess
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .claims import (
    ClaimRecord,
    EntailmentJudgement,
    TextVersionExtent,
    build_claim_evidence_audit,
    validate_evidence_audit_row,
)
from .corpus_loader import INGEST_METADATA_ONLY
from .data import REPO_ROOT, sha256_text, now_iso
from .models import (
    HYPOTHESIS_BAND,
    HYPOTHESIS_OPEN,
    NOT_ASSESSED,
    ROUTE_BASELINE,
    ROUTE_COUNTER,
    ROUTE_NEUTRAL,
    ROUTE_SUPPORT,
    UNKNOWN,
    ApplicabilityFlags,
    BiasAuditSummary,
    BudgetVector,
    CostModel,
    DocumentTextVersion,
    EVIDENCE_STATUS_VALUES,
    EvidenceAuditRow,
    FrozenCase,
    QueryTrace,
    RetrievalResult,
    RetrievalRun,
    RunArtifact,
    SourceDocument,
    VersionedChunk,
)

CODE_VERSION = "gate3-slice-0.1"
CHUNKER_VERSION = "ck-0.1"
INDEX_VERSION = "IX-0001-a"
QUERY_SET_VERSION = "QS-0001"
COST_MODEL_VERSION = "cost-0.1"
EMBEDDING_MODEL_ID = "none"

PIPELINE_BASELINE = "baseline"
PIPELINE_COMPETITIVE = "competitive"

#: The three route *intents* of the competitive decomposition
#: (``RETRIEVAL_DESIGN.md`` §4.2).  ``baseline_single`` is the baseline
#: pipeline's whole-query route for its *hypothesis* queries; it is never an
#: intent of the decomposition and never the route of an open-space probe.
ROUTE_INTENTS = (ROUTE_NEUTRAL, ROUTE_SUPPORT, ROUTE_COUNTER)

#: Suffix of the open-space marker ``<case_id>-H?`` (``DATA_SCHEMA.md`` §6.6:
#: when a query serves the open space the ``route`` must still be one of the
#: three route intents above).
OPEN_SPACE_MARKER_SUFFIX = "-H?"

#: Distributions this slice actually imports, with the importing module:
#: ``retrieval.py`` -> numpy / scikit-learn, ``data.py`` -> openpyxl.
_DEPENDENCY_DISTRIBUTIONS = ("numpy", "scikit-learn", "openpyxl")

#: Members required of the run manifest by ``DATA_SCHEMA.md`` §6.5A
#: (``run_manifest``) together with ``EVALUATION_PROTOCOL.md`` §10.
#: Members required of the run manifest by ``DATA_SCHEMA.md`` §6.5A
#: (``run_manifest``) together with the runtime identity fields.
MANIFEST_REQUIRED_MEMBERS = (
    "run_manifest_id",
    "run_id",
    "manifest_hash",
    "dependency_versions",
    "workspace_state",
    "random_seed",
    "corpus_version",
    "corpus_manifest_hash",
    "corpus_manifest_id",
    "index_version",
    "query_set_version",
    "query_set_manifest_hash",
    "gold_set_version",
    "gold_manifest_hash",
    "cost_model_version",
    "budget_limit_vector",
)

#: Cost model.  Weights are a ``[设计假设]``: template query construction has no
#: marginal cost under this model, so the charged unit is the number of
#: candidates retained for inspection/selection.  Baseline and competitive use
#: the *same* charged units by construction (see ``plan_queries``).
COST_MODEL = CostModel(
    version=COST_MODEL_VERSION,
    weights={"queries": 0.0, "candidates_scored": 1.0, "rerank_pairs": 1.0},
    unit_note=(
        "计费单位＝进入候选检查/选择阶段的候选数（baseline=top_k/查询；"
        "competitive=ceil(top_k/该组路由数)/查询，故同组总额相等）。"
        "查询构造为确定性模板，边际成本按 0 计；重排器未启用（rerank_pairs=0）。[设计假设]"
    ),
)

HONESTY_NOTES = (
    "语料为 metadata_only：仅有逐字法源名称，未取得官方全文；稀疏分数偏低属预期，不得解释为法律相关性。",
    "稠密通道未启用（dense_backend=none）：score_dense=NULL，本运行不声称混合检索已生效。",
    "重排器未启用（reranker=none）：score_rerank=NULL；authority_multiplier=NULL，位阶乘数 μ(d) 未定，本实现不预设。",
    "bridge_terms 为空：人工核验的桥接词表尚未建立（RETRIEVAL_DESIGN §10.2），不得机器自造，故 bridge_candidate 不置位。",
    "路由是检索意图，不是返回文档的标签；本运行不推断任何 support/counter 关系。",
    "本运行不产出评测分数；依赖 gold 的指标一律 not_assessed（no_gold）。",
)

#: Which corpus an index was built from.  The mode is *derived* from the
#: documents actually inside the index (``ingest_status``), never from a caller
#: flag, so an artefact cannot claim full text it does not contain.
CORPUS_MODE_FROZEN_METADATA = "frozen_metadata_only"
CORPUS_MODE_ACQUIRED_FULLTEXT = "acquired_full_text"

#: Honesty notes for an index built from the **acquired** corpus
#: (``corpus_loader``/``CV-0002``): real official full text is present, but the
#: channel is still sparse character TF-IDF and no gold exists.
CORPUS_HONESTY_NOTES = (
    "语料为真实获取的官方全文（逐来源 ingest_status=full_text）；获取失败的来源不进入索引、不做任何回填，"
    "故召回上限受获取结果约束。",
    "稠密通道未启用（dense_backend=none）：score_dense=NULL，本运行不声称混合检索已生效。",
    "重排器未启用（reranker=none）：score_rerank=NULL；authority_multiplier=NULL，位阶乘数 μ(d) 未定，本实现不预设。",
    "bridge_terms 为空：人工核验的桥接词表尚未建立（RETRIEVAL_DESIGN §10.2），不得机器自造，故 bridge_candidate 不置位。",
    "路由是检索意图，不是返回文档的标签；本运行不推断任何 support/counter 关系。",
    "本运行不产出评测分数；依赖 gold 的指标一律 not_assessed（no_gold）。",
)

#: Bias-audit warning paired with each corpus mode (kept honest per mode: the
#: frozen corpus really is metadata-only, an acquired index really is not).
CORPUS_MODE_WARNING = {
    CORPUS_MODE_FROZEN_METADATA: (
        "语料为 metadata_only：仅逐字法源名称，未取得官方全文；稀疏分数不得解释为法律相关性。"
    ),
    CORPUS_MODE_ACQUIRED_FULLTEXT: (
        "语料为真实获取的官方全文，但检索仍为稀疏字符 TF-IDF（无稠密通道、无重排）；"
        "分数不得解释为法律相关性，缺失来源导致的漏检不得读作『不存在该规范』。"
    ),
}


def corpus_mode_of(documents: Sequence[SourceDocument]) -> str:
    """Derive the corpus mode from the documents an index actually contains."""
    statuses = {document.ingest_status for document in documents}
    if not statuses:
        return UNKNOWN
    if statuses <= {INGEST_METADATA_ONLY}:
        return CORPUS_MODE_FROZEN_METADATA
    return CORPUS_MODE_ACQUIRED_FULLTEXT


def honesty_notes(corpus_mode: str) -> Tuple[str, ...]:
    """The honesty-note set matching ``corpus_mode`` (frozen notes as default)."""
    if corpus_mode == CORPUS_MODE_ACQUIRED_FULLTEXT:
        return CORPUS_HONESTY_NOTES
    return HONESTY_NOTES


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def build_versioned_chunks(
    documents: Sequence[SourceDocument],
    versions: Sequence[DocumentTextVersion],
    corpus_version: str,
) -> List[VersionedChunk]:
    """One versioned chunk per metadata-only document.

    Spans are Unicode code-point half-open intervals ``[start, end)`` into the
    chunk's ``text_version_id`` text.  ``embedding_text`` carries heading +
    text only — never a hypothesis id, relation label or gold flag.
    """
    version_by_doc = {item.doc_id: item for item in versions}
    chunks: List[VersionedChunk] = []
    for document in documents:
        version = version_by_doc[document.doc_id]
        text = version.normalized_text
        if not text:
            continue
        heading = document.title
        embedding_text = f"{heading}；{text}" if heading and heading != text else text
        chunk = VersionedChunk(
            chunk_id=f"{document.doc_id}-C0001@{CHUNKER_VERSION}",
            doc_id=document.doc_id,
            text_version_id=version.text_version_id,
            source_scope_id=document.source_scope_id,
            ordinal=0,
            heading=heading,
            chunk_type="unknown",
            span_start=0,
            span_end=len(text),
            chunk_text=text,
            chunk_sha256=sha256_text(text),
            embedding_text=embedding_text,
            embedding_text_sha256=sha256_text(embedding_text),
            char_count=len(text),
            overlap_prev_chars=0,
            chunker_version=CHUNKER_VERSION,
            corpus_version=corpus_version,
            structure_confidence="unknown",
            leakage_guard_ok=_leakage_guard_ok(embedding_text),
        )
        if version.normalized_text[chunk.span_start : chunk.span_end] != text:
            raise AssertionError(f"span mismatch for {chunk.chunk_id}")
        chunks.append(chunk)
    return chunks


def _leakage_guard_ok(embedding_text: str) -> bool:
    """Reject any hypothesis/relation token that must never enter the index."""
    banned = (
        "hypothesis_id",
        "stance",
        "is_gold",
        "gold_status",
        "CASE-0",
        "-H1",
        "-H2",
        "-H3",
        "-H4",
        "-H5",
        "-H6",
    )
    return not any(token in embedding_text for token in banned)


# ---------------------------------------------------------------------------
# Sparse index
# ---------------------------------------------------------------------------


@dataclass
class SparseTfidfIndex:
    documents: Sequence[SourceDocument]
    chunks: Sequence[VersionedChunk]
    corpus_version: str = "CV-0001"
    index_version: str = INDEX_VERSION
    chunker_version: str = ""

    def __post_init__(self) -> None:
        # Corpus provenance is derived from the actual chunk records, never
        # from a caller flag or a module constant.
        versions = {
            str(getattr(chunk, "chunker_version", "") or "")
            for chunk in self.chunks
            if str(getattr(chunk, "chunker_version", "") or "")
        }
        if len(versions) > 1:
            raise ValueError(f"mixed chunker versions in index: {sorted(versions)}")
        derived = next(iter(versions), "")
        if self.chunker_version and derived and self.chunker_version != derived:
            raise ValueError(
                f"index chunker_version={self.chunker_version!r} != chunks {derived!r}"
            )
        self.chunker_version = self.chunker_version or derived or CHUNKER_VERSION
        corpus = [chunk.embedding_text for chunk in self.chunks]
        self.vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(2, 5),
            min_df=1,
            sublinear_tf=True,
        )
        self.matrix = self.vectorizer.fit_transform(corpus)
        self.doc_by_id = {document.doc_id: document for document in self.documents}
        self.case_by_doc = {
            document.doc_id: _case_from_scope(document.source_scope_id)
            for document in self.documents
        }
        self.lexical_backend = "tfidf_char"
        self.lexical_params = {"analyzer": "char", "ngram_range": [2, 5], "sublinear_tf": True, "min_df": 1}
        self.embedding_model_id = EMBEDDING_MODEL_ID
        # Derived from the documents actually indexed, never from a caller flag.
        self.corpus_mode = corpus_mode_of(self.documents)
        self.ingest_status_counts: Dict[str, int] = {}
        for document in self.documents:
            self.ingest_status_counts[document.ingest_status] = (
                self.ingest_status_counts.get(document.ingest_status, 0) + 1
            )

    def score(self, query_text: str) -> np.ndarray:
        if not query_text or not query_text.strip():
            return np.zeros(len(self.chunks), dtype=float)
        return self.vectorizer.transform([query_text]).dot(self.matrix.T).toarray()[0]

    def candidate_indices(self, case_id: str) -> List[int]:
        return [
            index
            for index, chunk in enumerate(self.chunks)
            if self.case_by_doc.get(chunk.doc_id) == case_id
        ]

    def to_dict(self) -> Dict[str, object]:
        return {
            "index_version": self.index_version,
            "corpus_version": self.corpus_version,
            "corpus_mode": self.corpus_mode,
            "ingest_status_counts": dict(self.ingest_status_counts),
            "chunker_version": self.chunker_version,
            "lexical_backend": self.lexical_backend,
            "lexical_params": self.lexical_params,
            "embedding_model_id": self.embedding_model_id,
            "dense_status": "not_assessed (optional backend, not installed/verified; never claimed active)",
            "reranker_status": "not_assessed (not enabled)",
            "chunk_count": len(self.chunks),
            "doc_count": len(self.documents),
        }


def _case_from_scope(source_scope_id: str) -> str:
    """``SRC-AUTH-CASE03-04`` -> ``CASE-03``."""
    body = source_scope_id.replace("SRC-AUTH-", "")
    parts = body.split("-")
    if len(parts) >= 2 and parts[0].startswith("CASE"):
        return f"{parts[0][:4]}-{parts[0][4:]}"
    return UNKNOWN


# ---------------------------------------------------------------------------
# Configuration and query planning
# ---------------------------------------------------------------------------


@dataclass
class RetrievalConfig:
    top_k: int = 6
    r_min: int = 1
    min_score: float = 0.0
    candidate_pool: str = "case_source_scope"
    dense_backend: str = "none"
    reranker: str = "none"
    bridge_terms: Tuple[str, ...] = ()
    include_open_space_probe: bool = True

    def group_cap(self, route_count: int) -> int:
        return max(self.r_min, math.ceil(self.top_k / max(1, route_count)))

    def to_dict(self, chunker_version: str = CHUNKER_VERSION) -> Dict[str, object]:
        return {
            "top_k": self.top_k,
            "r_min": self.r_min,
            "min_score": self.min_score,
            "candidate_pool": self.candidate_pool,
            "dense_backend": self.dense_backend,
            "reranker": self.reranker,
            "bridge_terms": list(self.bridge_terms),
            "include_open_space_probe": self.include_open_space_probe,
            "chunker_version": chunker_version,
            "sparse_channel": "tfidf_char",
        }


@dataclass(frozen=True)
class QuerySpec:
    issue_id: str
    hypothesis_id: str
    route: str
    query_text: str
    route_rationale: str
    query_construction: str = "template"
    unknown_facts: Tuple[str, ...] = ()
    group_id: str = ""
    group_route_count: int = 1


def _issue_texts(case: FrozenCase) -> str:
    return " ".join(issue.issue_text for issue in case.issues)


def plan_queries(case: FrozenCase, pipeline: str, config: RetrievalConfig) -> List[QuerySpec]:
    """Deterministic query plan.  Routes are intents, never relation labels."""
    specs: List[QuerySpec] = []
    summary = case.case.summary
    issue_text = _issue_texts(case)
    is_baseline = pipeline == PIPELINE_BASELINE
    competing = [h for h in case.hypotheses if h.hypothesis_status != HYPOTHESIS_OPEN]

    for issue in case.issues:
        for hypothesis in case.hypotheses:
            group_id = f"{issue.issue_id}::{hypothesis.hypothesis_id}"
            if is_baseline:
                specs.append(
                    QuerySpec(
                        issue_id=issue.issue_id,
                        hypothesis_id=hypothesis.hypothesis_id,
                        route=ROUTE_BASELINE,
                        query_text=f"{summary} {issue.issue_text} {hypothesis.text}",
                        route_rationale=(
                            "单查询基线：案件事实 + 冻结争点原文 + 一条冻结假设，不拆路由、无重排、无融合。"
                        ),
                        group_id=group_id,
                        group_route_count=1,
                    )
                )
                continue

            others = [item for item in competing if item.hypothesis_id != hypothesis.hypothesis_id]
            if hypothesis.hypothesis_status == HYPOTHESIS_BAND:
                neighbours = [
                    item
                    for item in case.hypotheses
                    if item.hypothesis_status == HYPOTHESIS_BAND
                    and abs(item.ordinal - hypothesis.ordinal) == 1
                ]
                counter_pool = neighbours or others
                counter_note = "该档位假设为团队假设；反证路取相邻档位的排他条件（冻结原文）。"
            else:
                counter_pool = others or list(case.hypotheses)
                counter_note = "反证路取同案其他冻结竞争假设原文（其本身即对立解释）。"

            open_space_note = (
                "该假设为未决解释空间（hypothesis_status=unresolved_interpretive_space）：三路查询用于暴露分歧材料，"
                "不得改写为某一具体教义主张。"
                if hypothesis.hypothesis_status == HYPOTHESIS_OPEN
                else ""
            )

            specs.append(
                QuerySpec(
                    issue_id=issue.issue_id,
                    hypothesis_id=hypothesis.hypothesis_id,
                    route=ROUTE_NEUTRAL,
                    query_text=f"{issue.issue_text} {summary}",
                    route_rationale=(
                        "该争点下的裁判规则本身（构成要件、一般原则、程序规则）；"
                        "查询仅由冻结争点原文与案件简介原文拼接，不预设结论。" + open_space_note
                    ),
                    group_id=group_id,
                    group_route_count=3,
                )
            )
            specs.append(
                QuerySpec(
                    issue_id=issue.issue_id,
                    hypothesis_id=hypothesis.hypothesis_id,
                    route=ROUTE_SUPPORT,
                    query_text=f"{issue.issue_text} {hypothesis.text}",
                    route_rationale=(
                        "在冻结假设成立的假定下所需的事实与规范要素；查询由冻结争点原文与冻结假设原文拼接。"
                        + ("该假设为团队假设档位，故仅针对其构成条件。" if hypothesis.hypothesis_status == HYPOTHESIS_BAND else "")
                        + open_space_note
                    ),
                    group_id=group_id,
                    group_route_count=3,
                )
            )
            specs.append(
                QuerySpec(
                    issue_id=issue.issue_id,
                    hypothesis_id=hypothesis.hypothesis_id,
                    route=ROUTE_COUNTER,
                    query_text=f"{issue.issue_text} " + " ".join(item.text for item in counter_pool),
                    route_rationale=(
                        "削弱/区分该假设的信息需求。" + counter_note + "未新增任何机器自造法律词表。" + open_space_note
                    ),
                    group_id=group_id,
                    group_route_count=3,
                )
            )

    if config.include_open_space_probe:
        probe_terms = [item.item for item in case.unknown_facts]
        probe_text = " ".join([issue_text, case.open_marker.note, " ".join(probe_terms)]).strip()
        specs.append(
            QuerySpec(
                issue_id=case.issues[0].issue_id if case.issues else UNKNOWN,
                hypothesis_id=case.open_marker.marker_id,
                # GC-06: the probe serves the open space, so ``DATA_SCHEMA.md:574``
                # (``query_trace``) requires ``route`` to stay one of the three
                # route intents — in *both* pipelines.  ``counter_weakening`` is
                # the design's own home for this probe: ``RETRIEVAL_DESIGN.md``
                # §4.2 lists 「未知事实探针」 among the ``counter_weakening``
                # construction points, and §2.3 invariant 5 requires an explicit
                # ``H?`` downgrade instead of a high-certainty lean, i.e. the
                # probe asks for weakening/distinguishing material, not support.
                # ``baseline_single`` stays the baseline's *hypothesis* route.
                route=ROUTE_COUNTER,
                query_text=probe_text,
                route_rationale=(
                    "未决空间探针：<case>-H? 表示关键事实/规则未决，用于抑制高确定性倾向；"
                    "路由意图取 counter_weakening（RETRIEVAL_DESIGN §4.2 把「未知事实探针」列入该路构造要点，"
                    "§2.3 不变量 5 要求存在关键未决事实时显式降级），故 H? 查询的 route 仍为三路意图之一"
                    "（DATA_SCHEMA §6.6），在 baseline 与 competitive 两条管线上一致。"
                    "H? 不是假设实例，也永不进入 gold。"
                ),
                query_construction="template",
                unknown_facts=tuple(probe_terms) + (case.open_marker.note,),
                group_id=f"{case.case_id}-H?::probe",
                group_route_count=1,
            )
        )
    return specs


def validate_query_route_intents(queries: Sequence[QueryTrace]) -> None:
    """Invariant for ``DATA_SCHEMA.md:574`` / ``GC-06``.

    A query trace that serves the open space (``hypothesis_id`` = ``<case>-H?``)
    must carry one of the three route intents (:data:`ROUTE_INTENTS`); the
    baseline's whole-query route ``baseline_single`` must never appear together
    with an ``H?`` marker.  Raises ``AssertionError`` on the first violation.
    """
    for trace in queries:
        if trace.hypothesis_id.endswith(OPEN_SPACE_MARKER_SUFFIX) and trace.route not in ROUTE_INTENTS:
            raise AssertionError(
                f"{trace.query_id}: open-space probe {trace.hypothesis_id!r} carries route "
                f"{trace.route!r}; DATA_SCHEMA §6.6 requires one of {ROUTE_INTENTS}"
            )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _run_id(pipeline: str, sequence: int) -> str:
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%dT%H%M%S%f%z")
    nonce = uuid.uuid4().hex[:12]
    return f"RUN-{stamp}-{nonce}-{sequence:03d}-{pipeline}"


def _config_hash(payload: Dict[str, object]) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _query_set_manifest_hash(specs: Sequence[QuerySpec]) -> str:
    """Content+order manifest hash of the query set (``DATA_SCHEMA.md:534``)."""
    blob = "\n".join(f"{spec.route}|{spec.group_id}|{spec.query_text}" for spec in specs)
    return sha256_text(blob)


def _manifest_hash(payload: Mapping[str, object]) -> str:
    """Hash of the *complete* run manifest (``DATA_SCHEMA.md:558``).

    Every manifest member except ``manifest_hash`` itself is covered, so any
    change to a member (dependency versions, workspace state, seed, versions,
    gold pair, cost-model version, budget limit) changes the hash.
    """
    return _config_hash({key: value for key, value in payload.items() if key != "manifest_hash"})


def _applicability_flags(document: SourceDocument) -> ApplicabilityFlags:
    return ApplicabilityFlags(
        validity=document.validity_status,
        jurisdiction=document.jurisdiction,
        doc_type=document.document_type,
    )


# ---------------------------------------------------------------------------
# Fixed budget cap (GC-03) — a pre-registered bound, never a usage snapshot
# ---------------------------------------------------------------------------


def planned_query_slots(case: FrozenCase, config: RetrievalConfig) -> int:
    """Query slots the most query-hungry plan the config permits would issue.

    ``RETRIEVAL_DESIGN.md`` §4.2 issues three intent routes per
    ``(issue × hypothesis)`` group, and rule 5 adds one ``<case_id>-H?`` probe
    query, so the competitive plan is the widest plan in the pairing.
    """
    groups = len(case.issues) * len(case.hypotheses)
    return 3 * groups + (1 if config.include_open_space_probe else 0)


def fixed_budget_limit(case: FrozenCase, config: RetrievalConfig) -> BudgetVector:
    """Pre-registered, pipeline-independent fixed cap for one case (GC-03).

    Design basis
    ------------
    * ``DATA_SCHEMA.md:539`` — ``budget_limit_vector`` is a **fixed upper bound**
      ``{queries, candidates_scored, rerank_pairs}`` and **paired pipelines must
      be identical**; ``DATA_SCHEMA.md:541,551`` — ``actual_usage_vector`` may sit
      below the limit and must not exceed it (per charged dimension).
    * ``EVALUATION_PROTOCOL.md:80`` (isolation rule 1) and
      ``RETRIEVAL_DESIGN.md`` §6.2 rule 1 — the paired pipelines share one
      ``cost_model_version``, one ``budget_limit_vector`` and one
      ``budget_limit_total``; competitive buys route coverage with *shallower*
      routes, not with a bigger total.

    Derivation — from ``(case, config)`` alone, never from what a run used
    ---------------------------------------------------------------------
    * ``queries``: the allowed slot count of the widest permitted plan,
      :func:`planned_query_slots`.
    * ``candidates_scored``: every allowed slot is granted the widest per-route
      allowance the config can produce, ``config.group_cap(1)``.  ``group_cap``
      is non-increasing in the route count, so ``group_cap(1) = max(r_min,
      top_k)`` dominates every ``group_cap(route_count)`` actually charged, and
      the group-level global retention ceiling (``top_k`` distinct chunks per
      group) can only lower the realized usage further.
    * ``rerank_pairs``: ``0`` while the reranker is disabled
      (``reranker=none``: nothing may be reranked); otherwise the same per-slot
      envelope, since every reranked pair is first a scored candidate.

    Because the result depends on ``(case, config)`` only, baseline and
    competitive always receive an identical cap.  The cap is an upper bound for
    both plans; for the shipped configuration (``top_k=6``, ``r_min=1``) it is
    strictly above both, since each of the three competitive routes is granted
    only ``ceil(top_k/3) < group_cap(1)`` and the baseline issues a single
    query per group.
    """
    slots = planned_query_slots(case, config)
    per_slot = config.group_cap(1)
    rerank_pairs = 0 if config.reranker == "none" else slots * per_slot
    return BudgetVector(
        queries=slots,
        candidates_scored=slots * per_slot,
        rerank_pairs=rerank_pairs,
    )


def _assert_within_budget(actual: BudgetVector, limit: BudgetVector, run_id: str) -> None:
    """``actual_usage_vector <= budget_limit_vector`` per dimension (DATA_SCHEMA:551)."""
    for dimension, used, cap in (
        ("queries", actual.queries, limit.queries),
        ("candidates_scored", actual.candidates_scored, limit.candidates_scored),
        ("rerank_pairs", actual.rerank_pairs, limit.rerank_pairs),
    ):
        if used > cap:
            raise AssertionError(
                f"{run_id}: actual_usage_vector.{dimension}={used} exceeds "
                f"budget_limit_vector.{dimension}={cap}"
            )


# ---------------------------------------------------------------------------
# Run manifest (GC-04) — every required member, hashed, machine-readable
# ---------------------------------------------------------------------------


def _dependency_versions() -> Dict[str, str]:
    """Installed versions of the distributions this slice imports.

    ``importlib.metadata`` is the only source: a distribution that is not
    installed is recorded as ``unknown`` — never guessed or invented.
    """
    versions: Dict[str, str] = {}
    for distribution in _DEPENDENCY_DISTRIBUTIONS:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = UNKNOWN
    versions["python"] = platform.python_version()
    return versions


def _git(root: Path, args: Sequence[str]) -> str:
    """Run one read-only git command; empty string when git/repo is unavailable."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def workspace_state(root: Optional[Path] = None) -> Dict[str, object]:
    """VCS/workspace state for the manifest — never any secret.

    Only the VCS kind, branch, commit and a *count* of changed paths are
    recorded: file names, remotes, environment variables and credentials are
    never read or printed.  When the workspace is not a git work tree (or git is
    unavailable) the state is explicit instead of empty.
    """
    base = Path(root) if root is not None else REPO_ROOT
    if _git(base, ["rev-parse", "--is-inside-work-tree"]) != "true":
        return {
            "vcs": "none",
            "note": (
                "workspace is not a git work tree (or git is unavailable); no branch/commit "
                "recorded. Only this explicit marker is captured — no file names, environment "
                "variables or credentials."
            ),
        }
    status_lines = [line for line in _git(base, ["status", "--porcelain"]).splitlines() if line.strip()]
    return {
        "vcs": "git",
        "branch": _git(base, ["rev-parse", "--abbrev-ref", "HEAD"]) or UNKNOWN,
        "commit": _git(base, ["rev-parse", "HEAD"]) or UNKNOWN,
        "dirty": bool(status_lines),
        "changed_path_count": len(status_lines),
        "note": (
            "branch/commit/dirty-count only; changed path names, remotes and credentials are "
            "deliberately not captured."
        ),
    }


def build_run_manifest(
    *,
    run_id: str,
    pipeline: str,
    case_id: str,
    index_version: str,
    corpus_version: str,
    config: Mapping[str, object],
    config_hash: str,
    query_set_version: str,
    query_set_manifest_hash: str,
    budget_limit_vector: BudgetVector,
    budget_limit_total: float,
    actual_usage_vector: BudgetVector,
    actual_cost: float,
    cost_model_version: str,
    code_version: str,
    started_at: str,
    finished_at: str,
    operator: str,
    status: str,
    chunker_version: str = CHUNKER_VERSION,
    embedding_model_id: str = EMBEDDING_MODEL_ID,
    reranker_model_id: str = "none",
    gold_set_version: Optional[str] = None,
    gold_manifest_hash: Optional[str] = None,
    random_seed: str = "deterministic",
    workspace_root: Optional[Path] = None,
    dependency_versions: Optional[Mapping[str, str]] = None,
    corpus_manifest_hash: Optional[str] = None,
    corpus_manifest_id: Optional[str] = None,
) -> Dict[str, object]:
    """Build the machine-readable run manifest and its content hash (GC-04).

    Members follow ``DATA_SCHEMA.md`` §6.5A (``run_manifest``) plus
    ``EVALUATION_PROTOCOL.md`` §10 ("see the §3 field list + …"): identity and
    version fields, the full ``config``, ``dependency_versions``,
    ``workspace_state`` (no secrets), ``random_seed``,
    ``corpus_version``/``index_version``, ``chunker_version``/
    ``embedding_model_id``/``reranker_model_id``, ``query_set_version``/
    ``query_set_manifest_hash``, the paired ``gold_set_version``/
    ``gold_manifest_hash`` (paired ``None`` when there is no gold — this slice
    never produces gold), ``cost_model_version``, the fixed
    ``budget_limit_vector``/``budget_limit_total``, the observed
    ``actual_usage_vector``/``actual_cost`` and their documented compatibility
    aliases ``budget_vector``/``total_budget``, and finally ``manifest_hash``
    over every member above.

    ``dependency_versions`` and ``workspace_state`` are captured from the live
    environment when not supplied; nothing is invented.
    """
    if (gold_set_version is None) != (gold_manifest_hash is None):
        raise AssertionError(
            "gold_set_version/gold_manifest_hash must be paired: "
            f"got {gold_set_version!r}/{gold_manifest_hash!r} (DATA_SCHEMA.md:551)"
        )
    payload: Dict[str, object] = {
        "run_manifest_id": f"MANIFEST-{run_id}",
        "run_id": run_id,
        "pipeline": pipeline,
        "case_id": case_id,
        "code_version": code_version,
        "config": dict(config),
        "config_hash": config_hash,
        "dependency_versions": dict(
            dependency_versions if dependency_versions is not None else _dependency_versions()
        ),
        "workspace_state": workspace_state(workspace_root),
        "random_seed": random_seed,
        "corpus_version": corpus_version,
        "corpus_manifest_hash": corpus_manifest_hash,
        "corpus_manifest_id": corpus_manifest_id,
        "index_version": index_version,
        "chunker_version": chunker_version,
        "embedding_model_id": embedding_model_id,
        "reranker_model_id": reranker_model_id,
        "query_set_version": query_set_version,
        "query_set_manifest_hash": query_set_manifest_hash,
        "gold_set_version": gold_set_version,
        "gold_manifest_hash": gold_manifest_hash,
        "cost_model_version": cost_model_version,
        "budget_limit_vector": budget_limit_vector.to_dict(),
        "budget_limit_total": budget_limit_total,
        "actual_usage_vector": actual_usage_vector.to_dict(),
        "actual_cost": actual_cost,
        "budget_vector": actual_usage_vector.to_dict(),
        "total_budget": actual_cost,
        "started_at": started_at,
        "finished_at": finished_at,
        "operator": operator,
        "status": status,
    }
    payload["manifest_hash"] = _manifest_hash(payload)
    return payload


def persist_run_manifest(manifest: Mapping[str, object], directory: Path) -> Path:
    """Write the manifest as canonical JSON under ``directory`` (GC-04).

    The canonical artefact path (``run_smoke`` / ``app.py --json``) already
    carries the manifest inside each run; this writer is the on-disk form for
    run-directory tooling.  File name is deterministic:
    ``<run_id>.manifest.json``.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{manifest['run_id']}.manifest.json"
    if path.exists():
        raise FileExistsError(f"run manifest already exists; refusing overwrite: {path}")
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


@dataclass
class ManifestRunArtifact(RunArtifact):
    """``RunArtifact`` that carries its run manifest (GC-04).

    ``models.RunArtifact`` is the frozen schema record and is out of this
    slice's edit scope, so the manifest is attached here as an extra
    machine-readable member and surfaced by ``to_dict()``; every other member
    and behaviour is inherited unchanged.
    """

    run_manifest: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        data = super().to_dict()
        data["run_manifest"] = dict(self.run_manifest)
        return data


def run_retrieval(
    index: SparseTfidfIndex,
    case: FrozenCase,
    pipeline: str,
    config: Optional[RetrievalConfig] = None,
    run_sequence: int = 1,
    operator: str = "script:legal_rag.pipeline",
    manifest_dir: Optional[Path] = None,
    corpus_manifest_hash: Optional[str] = None,
) -> RunArtifact:
    """Execute one pipeline over one frozen case and return a traceable artefact.

    The returned artefact is a :class:`ManifestRunArtifact`: it carries the
    full run manifest (``DATA_SCHEMA.md`` §6.5A) and exposes it through
    ``to_dict()``, so every serialized run — ``run_smoke()``, ``app.py --json``
    — is machine-readably self-describing.  Passing ``manifest_dir`` also writes
    ``<manifest_dir>/<run_id>.manifest.json``.
    """
    config = config or RetrievalConfig()
    started_at = now_iso()
    run_id = _run_id(pipeline, run_sequence)
    specs = plan_queries(case, pipeline, config)
    pool = index.candidate_indices(case.case_id)

    queries: List[QueryTrace] = []
    results: List[RetrievalResult] = []
    group_selected: Dict[str, Dict[int, float]] = {}
    group_rows: Dict[str, List[RetrievalResult]] = {}
    result_counter = 0
    candidates_charged = 0

    for order, spec in enumerate(specs, start=1):
        query_id = f"{run_id}-Q{order:04d}"
        scores = index.score(spec.query_text)
        cap = config.group_cap(spec.group_route_count)
        candidates_charged += cap
        bucket = group_selected.setdefault(spec.group_id, {})
        queries.append(
            QueryTrace(
                query_id=query_id,
                run_id=run_id,
                case_id=case.case_id,
                issue_id=spec.issue_id,
                hypothesis_id=spec.hypothesis_id,
                route=spec.route,
                route_rationale=spec.route_rationale,
                query_text=spec.query_text,
                query_construction=spec.query_construction,
                retrieval_channel="sparse",
                top_k=cap,
                created_at=now_iso(),
                unknown_facts=list(spec.unknown_facts),
                filters={
                    "case_id": case.case_id,
                    "candidate_pool": config.candidate_pool,
                    "validity": UNKNOWN,
                    "jurisdiction": UNKNOWN,
                    "doc_type": UNKNOWN,
                },
                leakage_guard_ok=True,
            )
        )

        ranked = sorted(
            pool,
            key=lambda idx: (-float(scores[idx]), index.chunks[idx].chunk_id),
        )
        for rank, idx in enumerate(ranked, start=1):
            chunk = index.chunks[idx]
            document = index.doc_by_id[chunk.doc_id]
            raw = float(scores[idx])
            if rank <= cap and raw > config.min_score:
                bucket.setdefault(idx, raw)
                selected, omission = True, None
            elif raw > config.min_score:
                selected, omission = False, "budget_cut"
            else:
                selected, omission = False, "low_score"
            result_counter += 1
            row = RetrievalResult(
                result_id=f"{run_id}-R{result_counter:05d}",
                run_id=run_id,
                query_id=query_id,
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                source_scope_id=chunk.source_scope_id,
                text_version_id=chunk.text_version_id,
                span_start=chunk.span_start,
                span_end=chunk.span_end,
                route=spec.route,
                rank_raw=rank,
                rank_final=rank,
                score_sparse=raw,
                score_dense=None,
                score_fusion=raw,
                score_rerank=None,
                authority_multiplier=None,
                applicability_flags=_applicability_flags(document),
                selected=selected,
                omission_reason=omission,
                was_gold=NOT_ASSESSED,
            )
            results.append(row)
            group_rows.setdefault(spec.group_id, []).append(row)

    # Global per-group budget: keep at most top_k distinct chunks per group and
    # record every chunk dropped by that budget with an explicit omission reason.
    for group_id, bucket in group_selected.items():
        if len(bucket) <= config.top_k:
            continue
        keep = {
            idx
            for idx, _ in sorted(bucket.items(), key=lambda item: -item[1])[: config.top_k]
        }
        for row in group_rows.get(group_id, []):
            if row.selected and _chunk_index(index, row.chunk_id) not in keep:
                row.selected = False
                row.omission_reason = "budget_cut"
        group_selected[group_id] = {idx: bucket[idx] for idx in keep}

    finished_at = now_iso()
    actual_usage = BudgetVector(queries=len(specs), candidates_scored=candidates_charged, rerank_pairs=0)
    # GC-03: the cap is pre-registered from (case, config) and shared by both
    # pipelines of a pairing; it is *not* a snapshot of this run's usage.
    budget_limit = fixed_budget_limit(case, config)
    _assert_within_budget(actual_usage, budget_limit, run_id)
    validate_query_route_intents(queries)
    query_manifest_hash = _query_set_manifest_hash(specs)
    config_dict = config.to_dict(chunker_version=index.chunker_version)
    config_hash = _config_hash(config_dict)
    budget_limit_total = COST_MODEL.total(budget_limit)
    actual_cost = COST_MODEL.total(actual_usage)
    manifest = build_run_manifest(
        run_id=run_id,
        pipeline=pipeline,
        case_id=case.case_id,
        index_version=index.index_version,
        corpus_version=index.corpus_version,
        corpus_manifest_hash=corpus_manifest_hash,
        corpus_manifest_id=(
            f"{index.corpus_version}@{corpus_manifest_hash}"
            if corpus_manifest_hash
            else None
        ),
        config=config_dict,
        config_hash=config_hash,
        query_set_version=QUERY_SET_VERSION,
        query_set_manifest_hash=query_manifest_hash,
        budget_limit_vector=budget_limit,
        budget_limit_total=budget_limit_total,
        actual_usage_vector=actual_usage,
        actual_cost=actual_cost,
        cost_model_version=COST_MODEL_VERSION,
        code_version=CODE_VERSION,
        started_at=started_at,
        finished_at=finished_at,
        operator=operator,
        status="completed",
        chunker_version=index.chunker_version,
        embedding_model_id=index.embedding_model_id,
        reranker_model_id=config.reranker,
        gold_set_version=None,
        gold_manifest_hash=None,
        random_seed="deterministic",
    )
    if manifest_dir is not None:
        persist_run_manifest(manifest, Path(manifest_dir))
    run = RetrievalRun(
        run_id=run_id,
        pipeline=pipeline,
        case_id=case.case_id,
        index_version=index.index_version,
        corpus_version=index.corpus_version,
        config=config_dict,
        config_hash=config_hash,
        query_set_version=QUERY_SET_VERSION,
        query_set_manifest_hash=query_manifest_hash,
        budget_vector=actual_usage,
        cost_model_version=COST_MODEL_VERSION,
        total_budget=actual_cost,
        budget_limit_vector=budget_limit,
        budget_limit_total=budget_limit_total,
        actual_usage_vector=actual_usage,
        actual_cost=actual_cost,
        run_manifest_id=str(manifest["run_manifest_id"]),
        run_manifest_hash=str(manifest["manifest_hash"]),
        started_at=started_at,
        finished_at=finished_at,
        code_version=CODE_VERSION,
        operator=operator,
        status="completed",
        gold_set_version=None,
        gold_manifest_hash=None,
    )
    selected_results = [item for item in results if item.selected]
    bias_audit = build_bias_audit(run, queries, results, selected_results, index.corpus_mode)
    evidence_audit = build_evidence_audit(selected_results, index, finished_at)
    return ManifestRunArtifact(
        run=run,
        queries=queries,
        results=results,
        bias_audit=bias_audit,
        evidence_audit=evidence_audit,
        notes=list(honesty_notes(index.corpus_mode)),
        run_manifest=manifest,
    )


def _chunk_index(index: SparseTfidfIndex, chunk_id: str) -> int:
    for position, chunk in enumerate(index.chunks):
        if chunk.chunk_id == chunk_id:
            return position
    return -1


# ---------------------------------------------------------------------------
# Bias audit (descriptive risk signals only — never a fairness verdict)
# ---------------------------------------------------------------------------


def _entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((n / total) * math.log(n / total) for n in counts.values() if n)


def build_bias_audit(
    run: RetrievalRun,
    queries: Sequence[QueryTrace],
    results: Sequence[RetrievalResult],
    selected: Sequence[RetrievalResult],
    corpus_mode: str = CORPUS_MODE_FROZEN_METADATA,
) -> BiasAuditSummary:
    executed_routes = Counter(trace.route for trace in queries)
    routes_with_results = Counter(item.route for item in selected)
    coverage = {
        f"{route}": routes_with_results.get(route, 0) / executed_routes[route]
        for route in executed_routes
    }
    exposure = Counter(item.route for item in selected)
    total = sum(exposure.values())
    probs = [n / total for n in exposure.values()] if total else []
    hhi = sum(p * p for p in probs)
    entropy = _entropy(exposure)
    max_entropy = math.log(max(1, len(exposure)))
    source_diversity = Counter(item.source_scope_id for item in selected)
    warnings = [
        CORPUS_MODE_WARNING.get(corpus_mode, CORPUS_MODE_WARNING[CORPUS_MODE_FROZEN_METADATA]),
        "稠密通道与重排器均未启用：本运行不构成混合检索或重排性能结论。",
        "暴露熵/HHI 仅为描述性风险信号，不得表述为公平性结论，也不得据此推断司法不公。",
        "bridge_terms 为空，bridge_candidate 未置位：边缘案例桥接命中率 not_assessed。",
    ]
    if any(value < 1.0 for value in coverage.values()):
        warnings.append("部分（假设 × 路由）未召回任何候选：如实报告覆盖缺失，未补造。")
    if any(item.omission_reason == "budget_cut" for item in results):
        warnings.append("存在因固定预算被截断的候选，已写入 omission_reason=budget_cut 供偏置分析。")
    return BiasAuditSummary(
        run_id=run.run_id,
        metrics={
            "executed_query_count": len(queries),
            "result_row_count": len(results),
            "selected_result_count": len(selected),
            "distinct_selected_chunks": len({item.chunk_id for item in selected}),
            "distinct_selected_sources": len({item.source_scope_id for item in selected}),
            "exposure_by_route": dict(exposure),
            "exposure_entropy": entropy,
            "exposure_hhi": hhi,
            "exposure_imbalance": 1.0 - (entropy / max_entropy if max_entropy else 1.0),
            "source_diversity": dict(source_diversity),
            "authority_coverage": "not_assessed (authority_tier=unknown for every indexed document)",
        },
        undefined_metrics={
            "gold_recall@k": "no_gold",
            "counter_recall@k": "no_gold",
            "graded_ndcg@k": "no_gold",
            "mrr": "no_gold",
            "omitted_gold_rate": "no_gold",
            "substantive_hypothesis_coverage": "no_gold",
            "bridge_hit_rate": "not_assessed",
        },
        route_coverage={
            "executed_routes": dict(executed_routes),
            "routes_with_results": dict(routes_with_results),
            "ratio": coverage,
            "note": "route_query_coverage 是机器事实（是否返回候选），不是实质假设覆盖。",
        },
        substantive_coverage={"status": NOT_ASSESSED, "reason": "no_gold"},
        omitted_gold={"status": NOT_ASSESSED, "reason": "no_gold"},
        warnings=warnings,
        computed_at=now_iso(),
    )


# ---------------------------------------------------------------------------
# Evidence audit — five independent dimensions, never a fused score
# ---------------------------------------------------------------------------


def build_evidence_audit(
    selected: Sequence[RetrievalResult],
    index: SparseTfidfIndex,
    audited_at: str,
    claims: Sequence[ClaimRecord] = (),
    entailments: Optional[Mapping[str, EntailmentJudgement]] = None,
) -> List[EvidenceAuditRow]:
    """D1–D4 for every selected result, plus D5 for validly-linked claims.

    D5 is claim-scoped: ``claim_entailment`` rows are produced only by
    :func:`legal_rag.claims.build_claim_evidence_audit`, only for claims whose
    evidence edge resolved to ``linked`` against these results
    (``DATA_SCHEMA.md`` §6.9 「维度目标约束」/「主张—证据闭合约束」).  With no claim
    records there is no evidence edge, so the run carries no D5 row and never a
    fabricated entailment.
    """
    rows: List[EvidenceAuditRow] = []

    def _add(row: EvidenceAuditRow) -> None:
        allowed = EVIDENCE_STATUS_VALUES[row.dimension]
        if row.status not in allowed:
            raise AssertionError(
                f"evidence_audit.status {row.status!r} not allowed for {row.dimension}: {allowed}"
            )
        # DATA_SCHEMA.md §6.9 「目标互斥约束」/「维度目标约束」.
        validate_evidence_audit_row(row)
        rows.append(row)

    for item in selected:
        document = index.doc_by_id[item.doc_id]
        _add(
            EvidenceAuditRow(
                dimension="existence",
                status="unknown",
                method="whitelist_lookup",
                result_id=item.result_id,
                audited_at=audited_at,
                detail={
                    "extracted_citation": document.title,
                    "whitelist_source": "frozen source scope (human_status=pending_human_confirmation)",
                    "format_ok": None,
                    "reason": "权威白名单本身未经人工确认，未覆盖即不得判 fail。",
                },
            )
        )
        _add(
            EvidenceAuditRow(
                dimension="validity",
                status=NOT_ASSESSED,
                method="rule_regex",
                result_id=item.result_id,
                audited_at=audited_at,
                detail={
                    "as_of_date": UNKNOWN,
                    "relation_ids": [],
                    "validity_source": None,
                    "reason": "未执行时效核验；validity_status=unknown 不得默认 in_force。",
                },
            )
        )
        _add(
            EvidenceAuditRow(
                dimension="jurisdiction_applicability",
                status=NOT_ASSESSED,
                method="human_review",
                result_id=item.result_id,
                audited_at=audited_at,
                detail={
                    "case_jurisdiction": UNKNOWN,
                    "doc_jurisdiction": document.jurisdiction,
                    "matched_constraints": [],
                    "unmatched_constraints": [],
                    "reason": "适用性为法律判断，无人工确认时不得给肯定结论。",
                },
            )
        )
        _add(
            EvidenceAuditRow(
                dimension="quotation_fidelity",
                status=NOT_ASSESSED,
                method="offset_match",
                result_id=item.result_id,
                audited_at=audited_at,
                detail={
                    "text_version_id": item.text_version_id,
                    "span_start": item.span_start,
                    "span_end": item.span_end,
                    "match_ratio": None,
                    "reason": "本次运行未生成任何被核验引述文本，故不执行定位匹配。",
                },
            )
        )
    # D5 is claim-scoped. A claim_entailment row is emitted only for a claim whose
    # evidence edge resolved to ``linked`` against these results; the prototype run
    # itself carries no claim_record, hence no edge and no fabricated entailment.
    for row in build_claim_evidence_audit(
        claims,
        results=selected,
        text_versions=TextVersionExtent.from_chunks(index.chunks),
        audited_at=audited_at,
        entailments=entailments,
    ):
        _add(row)
    return rows
