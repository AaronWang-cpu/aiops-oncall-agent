"""Program-owned report header plus four-section Markdown body.

报告头部由程序固定，模型只负责正文。正文无效时直接使用程序兜底，不请求修正，
也不在报告中首次补出未验证的因果链。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from super_ai.aiops.diagnosis_models import (
    Hypothesis,
    HypothesisRelation,
    IncidentConclusion,
    QueryRecord,
    UnmetRequest,
)

REPORT_TITLE = "诊断报告"
ENGINE_LABEL = "假设驱动诊断（hypothesis-driven-v1）"

CONCLUSION_HEADING = "## 诊断结论"
EVIDENCE_HEADING = "## 原因与证据"
SCOPE_HEADING = "## 调查结果与局限"
ADVICE_HEADING = "## 后续建议"
BODY_HEADINGS = (CONCLUSION_HEADING, EVIDENCE_HEADING, SCOPE_HEADING, ADVICE_HEADING)

MOCK_NOTICE = "本报告基于项目内固定模拟场景，不代表真实线上观测。"
HISTORICAL_NOTICE = "以下正文基于此前一次有效判断，最新证据与解释尚未完成评估。"

STOP_REASON_LABELS = {
    "root_cause_confirmed": "已确认根因",
    "budget_exhausted": "预算用尽",
    "critical_data_unavailable": "关键数据不可用",
}
STATUS_LABELS = {
    "pending": "待调查",
    "investigating": "调查中",
    "supported": "有支持证据",
    "contradicted": "存在反证",
    "blocked": "受阻",
    "unresolved": "未解决",
}
RELATION_LABELS = {"causal_link": "因果关系", "competing": "竞争解释"}

# 仅在结论未确认时可检测的越界表述：模型不得自行宣布根因已确认。
_UNCONFIRMED_CONFLICT_PATTERNS = (
    re.compile(r"根因已确认"),
    re.compile(r"事故原因已确认"),
    re.compile(r"确认为(?:事故)?根因"),
)
_CODE_FENCE_START = "```"


def _empty_alert() -> dict[str, str]:
    return {}


@dataclass(frozen=True, slots=True)
class ReportFacts:
    """Everything the program may state without inventing new facts."""

    mode: Literal["real", "mock"]
    conclusion: IncidentConclusion | None
    hypotheses: tuple[Hypothesis, ...] = ()
    relations: tuple[HypothesisRelation, ...] = ()
    query_records: tuple[QueryRecord, ...] = ()
    unmet_requests: tuple[UnmetRequest, ...] = ()
    unassessed_evidence_ids: tuple[str, ...] = ()
    assessment_is_current: bool = True
    alert: dict[str, str] = field(default_factory=_empty_alert)
    limitations: tuple[str, ...] = ()
    generated_at: str = ""


@dataclass(frozen=True, slots=True)
class DiagnosisReport:
    title: str
    content: str
    body_source: Literal["model", "program"]


def build_diagnosis_report(*, facts: ReportFacts, model_body: str | None = None) -> DiagnosisReport:
    """Assemble the authoritative header with a model or program body."""
    body = model_body.strip() if isinstance(model_body, str) else ""
    if _model_body_is_usable(body, facts):
        source: Literal["model", "program"] = "model"
        selected_body = body
    else:
        source = "program"
        selected_body = _program_body(facts)
    header = _header(facts)
    return DiagnosisReport(
        title=REPORT_TITLE,
        content=f"{header}\n\n{selected_body}\n",
        body_source=source,
    )


def _model_body_is_usable(body: str, facts: ReportFacts) -> bool:
    if not body or body.startswith(_CODE_FENCE_START):
        return False
    positions = [body.find(heading) for heading in BODY_HEADINGS]
    if any(position < 0 for position in positions):
        return False
    if positions != sorted(positions):
        return False
    conclusion = facts.conclusion
    if conclusion is None or conclusion.conclusion_status != "confirmed":
        return not any(pattern.search(body) for pattern in _UNCONFIRMED_CONFLICT_PATTERNS)
    return True


def _header(facts: ReportFacts) -> str:
    lines = [f"# {REPORT_TITLE}", ""]
    conclusion = facts.conclusion
    if conclusion is not None and conclusion.conclusion_status == "confirmed":
        lines.append(f"- 事故结论：已确认根本原因 —— {conclusion.root_cause}")
    else:
        lines.append("- 事故结论：未确认根本原因")
    stop_reason = conclusion.stop_reason if conclusion is not None else None
    stop_label = STOP_REASON_LABELS.get(stop_reason, "未提供") if stop_reason else "未提供"
    lines.append(f"- 调查停止原因：{stop_label}")
    lines.append(f"- 判断时效：{'本次有效判断' if facts.assessment_is_current else '此前判断'}")
    lines.append(f"- 执行模式：{'真实连接' if facts.mode == 'real' else '模拟场景'}")
    lines.append(f"- 生成引擎：{ENGINE_LABEL}")
    lines.append(f"- 生成时间：{facts.generated_at or _now_text()}")
    alert_service = str(facts.alert.get("service") or "").strip()
    if alert_service:
        lines.append(f"- 告警服务：{alert_service}")
    if facts.mode == "mock":
        lines.append(f"- 说明：{MOCK_NOTICE}")
    if not facts.assessment_is_current:
        lines.append(f"- 说明：{HISTORICAL_NOTICE}")
    lines.append("")
    lines.append("---")
    return "\n".join(lines)


def _program_body(facts: ReportFacts) -> str:
    sections = [
        _conclusion_section(facts),
        _evidence_section(facts),
        _scope_section(facts),
        _advice_section(facts),
    ]
    return "\n\n".join(sections)


def _conclusion_section(facts: ReportFacts) -> str:
    conclusion = facts.conclusion
    if conclusion is None:
        return f"{CONCLUSION_HEADING}\n\n本次调查没有形成有效的事故结论。"
    if conclusion.conclusion_status == "confirmed":
        return (
            f"{CONCLUSION_HEADING}\n\n已确认根本原因：{conclusion.root_cause}\n\n"
            f"{conclusion.explanation}"
        )
    return f"{CONCLUSION_HEADING}\n\n本次调查未确认事故根本原因。\n\n{conclusion.explanation}"


def _evidence_section(facts: ReportFacts) -> str:
    lines = [EVIDENCE_HEADING, ""]
    if not facts.hypotheses:
        lines.append("本次调查未形成有依据的解释假设。")
    else:
        for hypothesis in facts.hypotheses:
            label = STATUS_LABELS.get(hypothesis.hypothesis_status, hypothesis.hypothesis_status)
            lines.append(f"- [{label}] {hypothesis.statement}")
            lines.append(f"  - 判断依据：{hypothesis.assessment}")
            if hypothesis.evidence_links:
                links = "；".join(
                    f"{link.evidence_id}（{_relation_text(link.relation)}）"
                    for link in hypothesis.evidence_links
                )
                lines.append(f"  - 关联证据：{links}")
            if hypothesis.gaps:
                gaps = "；".join(gap.question for gap in hypothesis.gaps)
                lines.append(f"  - 待查缺口：{gaps}")
    if facts.relations:
        lines.append("")
        lines.append("解释之间的关系：")
        for relation in facts.relations:
            lines.append(
                f"- {relation.from_hypothesis_id} → {relation.to_hypothesis_id}"
                f"（{RELATION_LABELS.get(relation.relation_type, relation.relation_type)}）："
                f"{relation.explanation}"
            )
    succeeded = sum(record.status == "succeeded" for record in facts.query_records)
    failed = len(facts.query_records) - succeeded
    lines.append("")
    lines.append(f"现场查询记录：成功 {succeeded} 次，失败 {failed} 次。")
    return "\n".join(lines)


def _scope_section(facts: ReportFacts) -> str:
    lines = [SCOPE_HEADING, ""]
    if facts.mode == "mock":
        lines.append(MOCK_NOTICE)
    if not facts.assessment_is_current:
        lines.append(HISTORICAL_NOTICE)
    if facts.unassessed_evidence_ids:
        lines.append(f"以下证据已保存但未纳入结论：{', '.join(facts.unassessed_evidence_ids)}。")
    if facts.unmet_requests:
        lines.append("未能覆盖的信息需求：")
        for request in facts.unmet_requests:
            lines.append(f"- {request.requirement}（原因：{request.reason}）")
    for limitation in facts.limitations:
        lines.append(f"- {limitation}")
    if len(lines) == 2:
        lines.append("本次调查未记录额外局限。")
    return "\n".join(lines)


def _advice_section(facts: ReportFacts) -> str:
    lines = [ADVICE_HEADING, ""]
    lines.append("本报告只总结已有分析，未执行任何处置动作。")
    conclusion = facts.conclusion
    if conclusion is not None and conclusion.conclusion_status == "confirmed":
        lines.append("请先核实该原因对应的具体变更或配置，再决定是否处置，并观察修复后指标。")
    else:
        lines.append("当前原因未确认，建议先补齐上方的待查缺口与未覆盖需求后再判断。")
    if facts.unmet_requests:
        lines.append("补齐信息需求时需具备相应工具能力，不以推测代替现场证据。")
    return "\n".join(lines)


def _relation_text(relation: str) -> str:
    return {"supports": "支持", "contradicts": "反证", "context": "背景"}.get(relation, relation)


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()
