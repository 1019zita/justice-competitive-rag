from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence, Tuple

from .models import Hypothesis, LegalDocument


DOMAIN_HYPOTHESES: Dict[str, List[Tuple[str, str]]] = {
    "正当防卫": [
        ("H1", "构成正当防卫"),
        ("H2", "构成防卫过当"),
        ("H3", "互殴或事后故意伤害，不构成防卫"),
        ("H?", "事实不足，暂不能判断"),
    ],
    "夫妻共同债务": [
        ("H1", "构成夫妻共同债务"),
        ("H2", "属于个人债务"),
        ("H?", "需要债权人进一步举证"),
    ],
    "好意同乘": [
        ("H1", "应当减轻驾驶人赔偿责任"),
        ("H2", "不减轻，存在故意或重大过失"),
        ("H?", "需要查明是否存在故意或重大过失"),
    ],
}


DOMAIN_CUES: Dict[str, Dict[str, Sequence[str]]] = {
    "正当防卫": {
        "element": ("正在进行", "侵害", "时间", "必要限度", "重大损害", "紧迫", "追击", "凶器", "持刀", "反击", "围堵", "攻击", "互殴"),
        "exception": ("特殊防卫", "行凶", "严重危及人身安全", "防卫挑拨"),
        "counter": ("侵害结束", "事后", "显著轻微", "重大过错", "不能认定为防卫"),
    },
    "夫妻共同债务": {
        "element": ("共同签名", "追认", "家庭日常生活", "共同经营", "举证", "婚姻关系"),
        "exception": ("婚前债务", "离婚", "死亡", "配偶账户"),
        "counter": ("个人名义", "超出", "不知情", "未用于家庭", "仅持股", "不足认定"),
    },
    "好意同乘": {
        "element": ("非营运", "无偿搭乘", "机动车一方责任", "减轻责任"),
        "exception": ("故意", "重大过失", "酒驾", "飙车", "未尽谨慎义务"),
        "counter": ("不减轻", "故意或重大过失", "严重过错", "超速", "醉驾"),
    },
}


def infer_domain(facts: str, documents: Iterable[LegalDocument]) -> str:
    scores = {domain: 0 for domain in DOMAIN_HYPOTHESES}
    for domain, cues in DOMAIN_CUES.items():
        for group in cues.values():
            scores[domain] += sum(1 for cue in group if cue in facts)
    if max(scores.values(), default=0) > 0:
        return max(scores, key=scores.get)
    domains = {doc.domain for doc in documents}
    return sorted(domains)[0] if domains else ""


def extract_issues(facts: str, domain: str) -> Tuple[List[str], List[str], List[str]]:
    cues = DOMAIN_CUES.get(domain, {})
    issues: List[str] = []
    known: List[str] = []
    unknown: List[str] = []
    for label, group in cues.items():
        present = [cue for cue in group if cue in facts]
        if present:
            issues.append(f"{label}: " + "、".join(present))
            known.extend(present)
    # Unknown facts are explicit omissions that frequently decide edge cases.
    missing_prompts = {
        "正当防卫": ["侵害是否已经结束", "是否存在主动追击", "损害后果是否达到重大损害", "双方力量与现场距离"],
        "夫妻共同债务": ["款项实际用途", "配偶是否知情或追认", "是否超出家庭日常生活需要", "债权人举证链"],
        "好意同乘": ["是否无偿搭乘", "驾驶人是否存在故意或重大过失", "事故责任比例", "车辆是否属于非营运机动车"],
    }
    for prompt in missing_prompts.get(domain, []):
        if not any(token in facts for token in prompt.replace("是否", "").replace("是否存在", "").split("/")):
            unknown.append(prompt)
    if not issues:
        issues.append("待从案件事实中进一步确定争议焦点")
    return issues, known, unknown


def generate_hypotheses(domain: str) -> List[Hypothesis]:
    return [Hypothesis(hypothesis_id=key, label=key, description=desc) for key, desc in DOMAIN_HYPOTHESES.get(domain, [("H?", "事实不足，暂不能判断")])]


def build_query_variants(facts: str, issue_text: str, hypothesis: Hypothesis, query_type: str, domain: str) -> List[str]:
    cues = DOMAIN_CUES.get(domain, {})
    if query_type == "neutral":
        anchors = cues.get("element", ())
    elif query_type == "counter":
        anchors = tuple(cues.get("counter", ())) + tuple(cues.get("exception", ()))
    else:
        anchors = tuple(cues.get("element", ())) + tuple(cues.get("exception", ()))
    # The second variant intentionally drops the hypothesis wording. This
    # catches cases whose facts are legally similar but lexically dissimilar.
    selected = [cue for cue in anchors if cue in facts or cue in hypothesis.description]
    if not selected:
        selected = list(anchors[:4])
    return [
        f"{facts} {issue_text} {hypothesis.description}",
        f"{domain} {' '.join(selected)} {query_type}",
    ]
