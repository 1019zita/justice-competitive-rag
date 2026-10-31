from __future__ import annotations

import math
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence

from .models import AuditReport, Hypothesis, LegalDocument, RetrievedEvidence


def _entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((n / total) * math.log(n / total) for n in counts.values() if n)


def build_audit(hypotheses: Sequence[Hypothesis], evidence: Dict[str, List[RetrievedEvidence]], documents: Sequence[LegalDocument], top_k: int = 6) -> AuditReport:
    by_id = {doc.doc_id: doc for doc in documents}
    coverage: Dict[str, float] = {}
    recall: Dict[str, Optional[float]] = {}
    all_edge: List[str] = []
    exposure = Counter()
    warnings: List[str] = []
    for hypothesis in hypotheses:
        items = evidence.get(hypothesis.hypothesis_id, [])
        top = items[:top_k]
        valid_items = [item for item in top if item.doc_id in by_id]
        covered_routes = sum(
            1 for route in ("neutral", "support", "counter")
            if any(item.query_type == route for item in valid_items)
        )
        coverage[hypothesis.hypothesis_id] = covered_routes / 3.0
        gold = [doc.doc_id for doc in documents if doc.is_gold is True and doc.stance_hypothesis.startswith(hypothesis.hypothesis_id)]
        if gold:
            hit = len(set(gold) & {item.doc_id for item in top})
            recall[hypothesis.hypothesis_id] = hit / len(gold)
        else:
            recall[hypothesis.hypothesis_id] = None
        for item in top:
            exposure[hypothesis.hypothesis_id] += 1
            if item.bridge_hit:
                all_edge.append(item.doc_id)

    total = sum(exposure.values())
    probs = [n / total for n in exposure.values()] if total else []
    hhi = sum(p * p for p in probs)
    max_entropy = math.log(max(1, len(hypotheses)))
    entropy = _entropy(exposure)
    imbalance = 1.0 - (entropy / max_entropy if max_entropy else 1.0)
    if any(value < 1.0 for value in coverage.values()):
        warnings.append("部分竞争性假设未获得最低限度的证据覆盖，应补做定向检索。")
    if imbalance > 0.45:
        warnings.append("证据暴露明显集中于少数假设；这只是风险信号，需结合 gold 和法源层级复核。")
    if not any(doc.is_gold is True for doc in documents):
        warnings.append("当前工作簿没有 is_gold 列或有效标注，反证召回率暂不能作为正式指标。")
    return AuditReport(
        hypothesis_coverage=coverage,
        counter_evidence_recall=recall,
        exposure_entropy=entropy,
        exposure_hhi=hhi,
        exposure_imbalance=imbalance,
        edge_case_hits=sorted(set(all_edge)),
        warnings=warnings,
    )
