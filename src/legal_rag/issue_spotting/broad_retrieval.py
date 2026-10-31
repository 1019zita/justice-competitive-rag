"""Experimental shared-scope retrieval for issue refinement.

This deliberately does not call the formal frozen-case retrieval planner.  It
loads CV-0005, indexes all acquired chunks, and uses only candidate issue query
seeds.  The scope and exclusions are explicit in every trace.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Set

from ..corpus_loader import load_corpus
from ..retrieval import SparseTfidfIndex
from .models import RetrievalResult, RetrievalTrace


class BroadSparseRetriever:
    def __init__(
        self,
        corpus_dir: str | Path,
        *,
        scope_mode: str = "shared_experimental",
        top_k: int = 6,
        exclude_doc_ids: Sequence[str] = (),
    ) -> None:
        if scope_mode != "shared_experimental":
            raise ValueError("issue spotting broad retrieval requires shared_experimental scope")
        snapshot = load_corpus(corpus_dir)
        self.snapshot = snapshot
        self.scope_mode = scope_mode
        self.top_k = top_k
        self.exclude_doc_ids: Set[str] = set(exclude_doc_ids)
        all_documents = snapshot.indexed_documents
        self.documents = [
            document for document in all_documents if document.doc_id not in self.exclude_doc_ids
        ]
        self.chunks = [
            chunk for chunk in snapshot.chunks if chunk.doc_id not in self.exclude_doc_ids
        ]
        self.index = SparseTfidfIndex(
            documents=self.documents,
            chunks=self.chunks,
            corpus_version=snapshot.corpus_version,
            index_version=snapshot.index_version,
            chunker_version=snapshot.chunker_version,
        )
        self.indexed_doc_ids = sorted(document.doc_id for document in self.documents)
        self._doc_by_id = {document.doc_id: document for document in self.documents}

    def search(
        self,
        *,
        retrieval_id: str,
        candidate_issue_id: str,
        query: str,
        exclude_doc_ids: Sequence[str] | None = None,
    ) -> RetrievalTrace:
        requested_exclusions = (
            self.exclude_doc_ids if exclude_doc_ids is None else set(exclude_doc_ids)
        )
        if requested_exclusions != self.exclude_doc_ids:
            raise ValueError(
                "target exclusions must be fixed before fitting the sparse index"
            )
        scores = self.index.score(query)
        ranked = sorted(
            range(len(self.index.chunks)),
            key=lambda index: (-float(scores[index]), self.index.chunks[index].chunk_id),
        )
        results: List[RetrievalResult] = []
        for rank, index in enumerate(ranked, start=1):
            if len(results) >= self.top_k:
                break
            chunk = self.index.chunks[index]
            document = self._doc_by_id[chunk.doc_id]
            results.append(
                RetrievalResult(
                    result_id=f"{retrieval_id}-R{len(results) + 1:03d}",
                    query=query,
                    rank=rank,
                    score=float(scores[index]),
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    source_scope_id=chunk.source_scope_id,
                    text_version_id=chunk.text_version_id,
                    span_start=chunk.span_start,
                    span_end=chunk.span_end,
                    title=document.title,
                    snippet=chunk.chunk_text[:1200],
                )
            )
        return RetrievalTrace(
            retrieval_id=retrieval_id,
            candidate_issue_id=candidate_issue_id,
            query=query,
            results=results,
            corpus_version=self.snapshot.corpus_version,
            scope_mode=self.scope_mode,
            excluded_doc_ids=sorted(self.exclude_doc_ids),
            indexed_doc_ids=self.indexed_doc_ids,
        )

    def retrieve_for_issues(
        self,
        issues: Sequence,
        *,
        max_seeds_per_issue: int = 2,
    ) -> List[RetrievalTrace]:
        traces: List[RetrievalTrace] = []
        counter = 1
        for issue in issues:
            for query in issue.query_seeds[:max_seeds_per_issue]:
                traces.append(
                    self.search(
                        retrieval_id=f"IR-{counter:03d}",
                        candidate_issue_id=issue.issue_id,
                        query=query,
                    )
                )
                counter += 1
        return traces


def render_retrieval_summary(traces: Sequence[RetrievalTrace]) -> str:
    lines: List[str] = []
    for trace in traces:
        lines.append(
            f"[{trace.retrieval_id}] candidate_issue={trace.candidate_issue_id} query={trace.query} "
            f"scope={trace.scope_mode} corpus={trace.corpus_version}"
        )
        if not trace.results:
            lines.append("  (no result)")
            continue
        for result in trace.results:
            lines.append(
                f"  [{result.result_id}] rank={result.rank} score={result.score:.6f} "
                f"doc_id={result.doc_id} title={result.title}\n    {result.snippet}"
            )
    return "\n".join(lines)
