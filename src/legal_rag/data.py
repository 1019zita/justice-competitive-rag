"""Loader for the two frozen canonical inputs.

Canonical inputs (``docs/02_design/CASE_RESEARCH_CONTRACT.md`` §0):

* ``原始资料/案件.xlsx``            — three frozen cases, their issues,
  hypotheses and listed legal authorities.
* ``原始资料/最终确定的法律数据库.png`` — the 17-entry source-scope list
  (transcribed once; the image carries no URL / access / subscription data).

``原始资料/司法AI法源池_3争议领域-AI生成-不作正式使用.xlsx`` is **legacy and
non-canonical** (AI-generated, explicitly marked 不作正式使用).  Nothing in this
module reads it, and no canonical case data may be taken from it.

Nothing here invents legal text, URLs, access status, validity or gold labels.
Every unverified field stays ``"unknown"`` and every transcribed record is
``machine_status="extracted_from_frozen_input"`` with
``human_status="pending_human_confirmation"``.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from openpyxl import load_workbook

from .models import (
    MACHINE_STATUS_CANDIDATE,
    MACHINE_STATUS_EXTRACTED,
    MACHINE_STATUS_UNKNOWN,
    HYPOTHESIS_BAND,
    HYPOTHESIS_BINARY,
    HYPOTHESIS_OPEN,
    UNKNOWN,
    CaseRecord,
    DocumentTextVersion,
    FactorRecord,
    FrozenCase,
    FrozenCorpus,
    HypothesisRecord,
    IssueRecord,
    OpenSpaceMarker,
    Provenance,
    SourceAuthorityScope,
    SourceDocument,
    SourceRepository,
    UnknownFact,
)

LOADER_VERSION = "data-0.1"
CORPUS_VERSION = "CV-0001"

REPO_ROOT = Path(__file__).resolve().parents[2]
FROZEN_CASE_WORKBOOK = REPO_ROOT / "原始资料" / "案件.xlsx"
FROZEN_SOURCE_SCOPE_IMAGE = REPO_ROOT / "原始资料" / "最终确定的法律数据库.png"

CASE_SHEET = "Sheet1"
HEADER_ROW = 1
COL_CASE_NAME = "案件名称"
COL_DOMAIN = "部门法"
COL_SUMMARY = "案件简介"
COL_ISSUE = "争议焦点"
COL_SOURCE_NAME = "法源名称"
COL_SOURCE_PUBLISHER = "制定 / 发布机构"
COL_SOURCE_TYPE = "法源类型"
HYPOTHESIS_COLUMNS = ("H1", "H2", "H3", "H4", "H5", "H6")

#: ``案件.xlsx`` case rows, in frozen order (verified against the workbook).
CASE_SHORT_NAMES = {
    "CASE-01": "田永案",
    "CASE-02": "郑某诉吴某涉彩礼案",
    "CASE-03": "于海明案",
}

#: Workbook ``法源类型`` -> DATA_SCHEMA ``document_type`` enum.  The workbook
#: labels are unverified, so the mapping is a machine candidate, never gold.
DOCUMENT_TYPE_MAP = {
    "法律": "statute",
    "行政法规": "administrative_regulation",
    "部门规章": "departmental_rule",
    "司法解释": "judicial_interpretation",
    "指导性案例": "guiding_case",
    "公报案例": "gazette_case",
    "联合规范性司法文件（司法解释性质）": "normative_document",
}

#: 17 source-scope names, transcribed verbatim from
#: ``原始资料/最终确定的法律数据库.png`` (single-column list; verified twice).
#: ``(name, platform_class_machine_candidate, jurisdiction_machine_candidate)``
SOURCE_DATABASE_NAMES: Sequence[Tuple[str, str, str]] = (
    ("国家法律法规数据库", "官方公开入口", "中国大陆"),
    ("中国裁判文书网", "官方公开入口", "中国大陆"),
    ("人民法院案例库", "官方公开入口", "中国大陆"),
    ("国家行政法规库", "官方公开入口", "中国大陆"),
    ("国家规章库", "官方公开入口", "中国大陆"),
    ("司法行政（法律服务）案例库", "官方公开入口", "中国大陆"),
    ("中国法律服务网", "官方公开入口", "中国大陆"),
    ("最高人民法院数字图书馆", "官方公开入口", "中国大陆"),
    ("北大法宝", "商业数据库", "中国大陆"),
    ("威科先行法律信息库", "商业数据库", "中国大陆"),
    ("法信", "商业数据库", "中国大陆"),
    ("无讼案例", "商业数据库", "中国大陆"),
    ("法律图书馆", "第三方平台", "中国大陆"),
    ("民商法律网", "第三方平台", "中国大陆"),
    ("Westlaw", "商业数据库", "域外（多法域）"),
    ("LexisNexis / Lexis+", "商业数据库", "域外（多法域）"),
    ("HeinOnline", "商业数据库", "域外（多法域）"),
)

#: CASE-02 unknown factual statuses, declared by the frozen design contract
#: (``docs/02_design/CASE_RESEARCH_CONTRACT.md`` §2.2).  They are ``unknown``,
#: never replaced by a hypothesis.
DECLARED_UNKNOWN_FACTS: Dict[str, Sequence[Tuple[str, str]]] = {
    "CASE-02": (
        (
            "双方是否实际共同生活、共同生活时长",
            "工作簿仅载明 3 月 4 日登记、3 月 6 日回到 B 省、3 月 14 日吴某离开；是否构成「共同生活」及起止时点未载明",
        ),
        ("彩礼 20 万元的用途与支出", "工作簿未载明是否用于共同生活"),
        ("是否存在借婚姻索取财物/骗婚等过错", "属当事人主张与法院认定事项，工作簿未载明认定结论"),
        ("给付人生活是否因给付彩礼而困难", "工作簿未载明"),
        ("女方是否怀孕、流产或生育子女", "工作簿未载明"),
        ("裁判文书编号、裁判日期、审级", "工作簿未载明"),
    ),
}

DECLARED_UNKNOWN_SOURCE = "CASE_RESEARCH_CONTRACT.md §2.2 (frozen design contract)"

_TEAM_BAND_NOTE = (
    "本条档位与百分比区间为团队设定的研究假设（[设计假设]），"
    "不是法律、司法解释、指导性案例或任何官方文件规定的返还标准，"
    "也不是统计推断结果；不得作为裁判规则引用。"
)

_BAND_RE = re.compile(r"返还\s*(\d+)\s*%\s*[~～\-–—]\s*(\d+)\s*%")
_BASELINE_RE = re.compile(r"（基准\s*(\d+)\s*%）")
_NUMBERED_LINE_RE = re.compile(r"^\s*\d+\s*[.、．]")
_OPEN_SPACE_MARKERS = (
    "解释空间",
    "缺乏细化规则",
    "缺乏实定法",
    "标准模糊",
    "无法直接得出唯一结论",
    "需价值权衡",
    "裁量弹性",
)


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _cell(row: Sequence, headers: Dict[str, int], name: str) -> Optional[str]:
    index = headers.get(name)
    if index is None:
        return None
    value = row[index - 1]
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _lines(text: str) -> List[str]:
    return [line.strip() for line in str(text).split("\n") if line.strip()]


def parse_issues_and_factors(case_id: str, cell_text: str) -> Tuple[List[IssueRecord], List[FactorRecord]]:
    """Split the workbook 争议焦点 cell into issues (and CASE-02 factors).

    The cell is a newline-separated list.  When the first line is unnumbered and
    the following lines are numbered, the first line is the single issue and the
    numbered lines are the supporting factors (CASE-02).  Otherwise every line
    is an issue, numbered in frozen order.
    """
    lines = _lines(cell_text)
    if not lines:
        return [], []

    numbered = [line for line in lines if _NUMBERED_LINE_RE.match(line)]
    issues_text: List[str] = []
    factors_text: List[str] = []

    if lines[0] and not _NUMBERED_LINE_RE.match(lines[0]) and numbered:
        issues_text = [lines[0]]
        factors_text = numbered
    elif numbered and len(numbered) == len(lines):
        issues_text = lines
    else:
        issues_text = lines

    issues: List[IssueRecord] = []
    factors: List[FactorRecord] = []
    for order, text in enumerate(issues_text, start=1):
        issue_id = f"{case_id}-ISS-{order:02d}"
        issues.append(
            IssueRecord(
                case_id=case_id,
                issue_id=issue_id,
                ordinal=order,
                issue_text=text,
            )
        )
    if issues:
        issue_id = issues[0].issue_id
        for order, text in enumerate(factors_text, start=1):
            is_adjustment = "档位" in text
            factor = FactorRecord(
                factor_id=f"{issue_id}-F{order:02d}",
                issue_id=issue_id,
                case_id=case_id,
                ordinal=order,
                text=text,
                factor_type="team_hypothesis_adjustment" if is_adjustment else "factual_contextual",
                statutory_basis="false" if is_adjustment else UNKNOWN,
            )
            factors.append(factor)
            issues[0].factors.append(factor)
    return issues, factors


def classify_hypothesis(text: str) -> Tuple[str, str, str, str, Optional[int]]:
    """Return ``(hypothesis_status, statutory_basis, status_basis, band_label, baseline_pct)``."""
    band = _BAND_RE.search(text)
    if band:
        baseline = _BASELINE_RE.search(text)
        band_label = _lines(text)[0] if _lines(text) else text
        return (
            HYPOTHESIS_BAND,
            "false",
            "keyword_rule:band_percentage",
            band_label,
            int(baseline.group(1)) if baseline else None,
        )
    if any(marker in text for marker in _OPEN_SPACE_MARKERS):
        return (
            HYPOTHESIS_OPEN,
            UNKNOWN,
            "keyword_rule:open_interpretive_space",
            "",
            None,
        )
    return HYPOTHESIS_BINARY, UNKNOWN, "keyword_rule:default_binary", "", None


def _document_type(document_type_as_written: str) -> Tuple[str, str]:
    for key, value in DOCUMENT_TYPE_MAP.items():
        if document_type_as_written == key or document_type_as_written.startswith(key):
            return value, MACHINE_STATUS_CANDIDATE
    return UNKNOWN, MACHINE_STATUS_UNKNOWN


def _verification_flags(title: str, publisher: str, type_as_written: str) -> List[str]:
    flags: List[str] = []
    if type_as_written == "行政法规" and "全国人大" not in publisher:
        flags.append("type_label_conflicts_with_issuing_body")
    if "典型案例" in title and type_as_written == "司法解释":
        flags.append("type_label_likely_misclassified_case_collection")
    if "法释" in type_as_written:
        flags.append("document_number_attribution_unverified")
    if re.search(r"(19\d{2}|1990)\s*年?版", title):
        flags.append("version_validity_unverified")
    flags.append("metadata_requires_human_check")
    return flags


def load_source_repositories(
    image_path: str | Path = FROZEN_SOURCE_SCOPE_IMAGE,
) -> List[SourceRepository]:
    """Register the 17 source-scope entries without claiming any access.

    The image is a scope declaration only: it carries no URL, access or
    subscription information, so those fields stay ``"unknown"``.
    """
    image_path = Path(image_path)
    if not image_path.is_absolute():
        image_path = REPO_ROOT / image_path
    if image_path.exists():
        provenance = Provenance(
            source_path=str(image_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            source_sha256=sha256_file(image_path),
            extraction_method="screenshot_transcription",
            extracted_at=now_iso(),
            note="单列名称清单的视觉转写；图像不含 URL / 访问条件 / 订阅状态。",
        )
    else:
        provenance = Provenance(
            source_path=str(image_path),
            source_sha256=UNKNOWN,
            extraction_method="screenshot_transcription",
            extracted_at=now_iso(),
            note="冻结图像不可读；沿用已核验的 17 项转写清单，来源哈希记为 unknown。",
        )
    repositories: List[SourceRepository] = []
    for order, (name, platform_class, jurisdiction) in enumerate(SOURCE_DATABASE_NAMES, start=1):
        repositories.append(
            SourceRepository(
                source_scope_id=f"SRC-DB-{order:02d}",
                order=order,
                name_zh=name,
                platform_class_machine_candidate=platform_class,
                jurisdiction_machine_candidate=jurisdiction,
                provenance=provenance,
            )
        )
    return repositories


def load_frozen_cases(
    case_workbook: str | Path = FROZEN_CASE_WORKBOOK,
    source_scope_image: str | Path = FROZEN_SOURCE_SCOPE_IMAGE,
    corpus_version: str = CORPUS_VERSION,
) -> FrozenCorpus:
    """Load the three frozen cases, their issues/hypotheses and source scope."""
    case_workbook = Path(case_workbook)
    if not case_workbook.is_absolute():
        case_workbook = REPO_ROOT / case_workbook
    if not case_workbook.exists():
        raise FileNotFoundError(f"冻结案件工作簿不存在: {case_workbook}")

    workbook = load_workbook(case_workbook, read_only=True, data_only=True)
    if CASE_SHEET not in workbook.sheetnames:
        raise ValueError(f"冻结工作簿缺少工作表 {CASE_SHEET!r}: {workbook.sheetnames}")
    worksheet = workbook[CASE_SHEET]
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        raise ValueError("冻结工作簿为空")

    header = rows[HEADER_ROW - 1]
    headers: Dict[str, int] = {
        str(value).strip(): index
        for index, value in enumerate(header, start=1)
        if value is not None
    }
    missing = [
        column
        for column in (COL_DOMAIN, COL_CASE_NAME, COL_SUMMARY, COL_ISSUE, COL_SOURCE_NAME)
        if column not in headers
    ]
    if missing:
        raise ValueError(f"冻结工作簿缺少必要列: {missing}")

    provenance = Provenance(
        source_path=str(case_workbook.relative_to(REPO_ROOT)).replace("\\", "/")
        if case_workbook.is_relative_to(REPO_ROOT)
        else str(case_workbook),
        source_sha256=sha256_file(case_workbook),
        extraction_method="xlsx_sheet_read",
        extracted_at=now_iso(),
        note=f"工作表 {CASE_SHEET}；逐字转写案件/争点/假设/法源，未改写法律假设。",
    )

    cases: List[FrozenCase] = []
    current: Optional[dict] = None

    def _finalize(state: dict) -> FrozenCase:
        case_id = state["case_id"]
        issues, _ = parse_issues_and_factors(case_id, state["issue_text"] or "")
        hypotheses: List[HypothesisRecord] = []
        for column in HYPOTHESIS_COLUMNS:
            text = state["hypotheses"].get(column)
            if not text:
                continue
            ordinal = int(column[1:])
            status, statutory, basis, band_label, baseline_pct = classify_hypothesis(text)
            hypotheses.append(
                HypothesisRecord(
                    case_id=case_id,
                    hypothesis_id=f"{case_id}-H{ordinal}",
                    ordinal=ordinal,
                    text=text,
                    hypothesis_status=status,
                    statutory_basis=statutory,
                    status_basis=basis,
                    band_label=band_label,
                    baseline_pct=baseline_pct,
                    team_hypothesis_note=_TEAM_BAND_NOTE if status == HYPOTHESIS_BAND else "",
                    machine_status=MACHINE_STATUS_EXTRACTED,
                )
            )
        if not hypotheses:
            raise ValueError(f"{case_id} 未解析出任何冻结假设")

        open_hypotheses = [h for h in hypotheses if h.hypothesis_status == HYPOTHESIS_OPEN]
        if open_hypotheses:
            marker_note = open_hypotheses[0].text
        else:
            marker_note = (
                "工作簿未给出档位之间的事实门槛如何由佐证因素组合确定，也未给出档位与因素之间的加权规则；"
                "档位选择规则本身属待研究问题，不是既定标准。"
            )
        open_marker = OpenSpaceMarker(
            case_id=case_id,
            marker_id=f"{case_id}-H?",
            note=marker_note,
        )

        unknown_facts = [
            UnknownFact(
                case_id=case_id,
                item=item,
                detail=detail,
                declared_by=DECLARED_UNKNOWN_SOURCE,
            )
            for item, detail in DECLARED_UNKNOWN_FACTS.get(case_id, ())
        ]

        scopes: List[SourceAuthorityScope] = []
        for order, (title, publisher, type_as_written) in enumerate(state["sources"], start=1):
            scopes.append(
                SourceAuthorityScope(
                    source_scope_id=f"SRC-AUTH-{case_id.replace('-', '')}-{order:02d}",
                    case_id=case_id,
                    order=order,
                    title=title,
                    publisher=publisher or UNKNOWN,
                    document_type_as_written=type_as_written or UNKNOWN,
                    verification_flags=_verification_flags(title, publisher or "", type_as_written or ""),
                )
            )

        integrity_note = ""
        if case_id == "CASE-02":
            integrity_note = (
                "official_case_status_unverified：工作簿未载明裁判文书编号与裁判日期；"
                "H1–H6 为团队假设档位，非法定标准。"
            )
        case_record = CaseRecord(
            case_id=case_id,
            display_name=state["case_name"],
            short_name=CASE_SHORT_NAMES.get(case_id, state["case_name"]),
            domain=state["domain"] or UNKNOWN,
            summary=state["summary"] or "",
            source_row_index=state["row_index"],
            integrity_note=integrity_note,
        )
        return FrozenCase(
            case=case_record,
            issues=issues,
            hypotheses=hypotheses,
            open_marker=open_marker,
            unknown_facts=unknown_facts,
            source_authority_scopes=scopes,
        )

    for row_index, row in enumerate(rows[HEADER_ROW:], start=HEADER_ROW + 1):
        case_name = _cell(row, headers, COL_CASE_NAME)
        source_name = _cell(row, headers, COL_SOURCE_NAME)
        if case_name:
            if current is not None:
                cases.append(_finalize(current))
            case_id = f"CASE-{len(cases) + 1:02d}"
            current = {
                "case_id": case_id,
                "case_name": case_name,
                "domain": _cell(row, headers, COL_DOMAIN) or "",
                "summary": _cell(row, headers, COL_SUMMARY) or "",
                "issue_text": _cell(row, headers, COL_ISSUE) or "",
                "row_index": row_index,
                "hypotheses": {
                    column: _cell(row, headers, column) for column in HYPOTHESIS_COLUMNS
                },
                "sources": [],
            }
        if current is None:
            continue
        if source_name:
            current["sources"].append(
                (
                    source_name,
                    _cell(row, headers, COL_SOURCE_PUBLISHER) or UNKNOWN,
                    _cell(row, headers, COL_SOURCE_TYPE) or UNKNOWN,
                )
            )
    if current is not None:
        cases.append(_finalize(current))

    repositories = load_source_repositories(source_scope_image)
    return FrozenCorpus(
        cases=cases,
        source_repositories=repositories,
        corpus_version=corpus_version,
        loader_version=LOADER_VERSION,
        provenance=[provenance, repositories[0].provenance],
        loaded_at=now_iso(),
    )


def build_source_documents(corpus: FrozenCorpus):
    """L1 document + text-version records for every frozen source authority.

    The frozen inputs carry bibliographic metadata only, so each document is
    ``ingest_status="metadata_only"`` and its text version is the verbatim
    authority title.  No full text is invented.
    """
    documents: List[SourceDocument] = []
    versions: List[DocumentTextVersion] = []
    for case in corpus.cases:
        for scope in case.source_authority_scopes:
            doc_id = f"DOC-{scope.source_scope_id}-0001"
            document_type, type_status = _document_type(scope.document_type_as_written)
            documents.append(
                SourceDocument(
                    doc_id=doc_id,
                    source_scope_id=scope.source_scope_id,
                    authority_role=scope.authority_role,
                    title=scope.title,
                    document_type=document_type,
                    document_type_as_written=scope.document_type_as_written,
                    document_type_status=type_status,
                    source_authority=scope.publisher,
                    first_seen_corpus_version=corpus.corpus_version,
                    not_retrieved_reason=(
                        "尚未执行来源获取：仅登记冻结工作簿给出的书目元数据，"
                        "未取得官方全文，未声明任何访问。"
                    ),
                )
            )
            versions.append(
                DocumentTextVersion(
                    text_version_id=f"{doc_id}-TV1",
                    doc_id=doc_id,
                    version_no=1,
                    normalizer_version="nz-0.1",
                    normalization_ops=["strip", "collapse_whitespace"],
                    normalized_text=scope.title,
                    text_sha256=sha256_text(scope.title),
                    char_length=len(scope.title),
                    extraction_loss_note="metadata_only：无官方全文，文本版本为逐字法源名称。",
                    created_at=corpus.loaded_at,
                )
            )
    return documents, versions
