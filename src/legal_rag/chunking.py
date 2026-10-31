from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List

from .models import LegalDocument


@dataclass
class LegalChunk:
    chunk_id: str
    doc_id: str
    ordinal: int
    text: str
    heading: str = ""
    chunk_type: str = "body"

    @property
    def embedding_text(self) -> str:
        # Include stable context, but never include gold stance labels in the
        # embedding text because they would leak evaluation annotations.
        context = "；".join(x for x in (self.heading, self.text) if x)
        return context

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；])\s*")
_ARTICLE = re.compile(r"(第[一二三四五六七八九十百千万0-9]+条(?:之[一二三四五六七八九十百千万0-9]+)?|[（(][一二三四五六七八九十百千万0-9]+[）)])")


def _segments(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    # Article markers are retained in the same segment, which prevents a
    # legal element from being separated from the article it qualifies.
    pieces = [piece.strip() for piece in _SENTENCE_SPLIT.split(text) if piece.strip()]
    return pieces or [text]


def chunk_document(doc: LegalDocument, max_chars: int = 360, overlap_chars: int = 60) -> List[LegalChunk]:
    """Create structure-aware chunks for statutes, guidance and case text.

    The current seed rows are short and normally produce one chunk. Longer
    source documents are packed by sentence up to ``max_chars``; an overlong
    sentence falls back to a sliding character window so it is never dropped.
    """
    sentences = _segments(doc.text)
    if not sentences:
        return []
    chunks: List[LegalChunk] = []
    buffer = ""
    ordinal = 0

    def emit(value: str) -> None:
        nonlocal ordinal
        value = value.strip()
        if not value:
            return
        chunks.append(
            LegalChunk(
                chunk_id=f"{doc.doc_id}::c{ordinal:03d}",
                doc_id=doc.doc_id,
                ordinal=ordinal,
                text=value,
                heading=doc.title,
                chunk_type="article" if _ARTICLE.search(value) else "body",
            )
        )
        ordinal += 1

    for sentence in sentences:
        if len(sentence) > max_chars:
            if buffer:
                emit(buffer)
                buffer = ""
            start = 0
            while start < len(sentence):
                end = min(len(sentence), start + max_chars)
                emit(sentence[start:end])
                if end == len(sentence):
                    break
                start = max(start + 1, end - overlap_chars)
            continue
        candidate = f"{buffer}{sentence}" if buffer else sentence
        if buffer and len(candidate) > max_chars:
            emit(buffer)
            tail = buffer[-overlap_chars:] if overlap_chars else ""
            buffer = f"{tail}{sentence}"
        else:
            buffer = candidate
    if buffer:
        emit(buffer)
    return chunks


def chunk_documents(documents: Iterable[LegalDocument], max_chars: int = 360, overlap_chars: int = 60) -> List[LegalChunk]:
    chunks: List[LegalChunk] = []
    for doc in documents:
        chunks.extend(chunk_document(doc, max_chars=max_chars, overlap_chars=overlap_chars))
    return chunks
