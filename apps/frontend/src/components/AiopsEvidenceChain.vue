<script setup lang="ts">
import { ChevronDown, GitBranch, Lightbulb, Wrench } from "lucide-vue-next";
import { computed, ref } from "vue";

const collapsed = ref(true);

import type {
  AiopsDiagnosticEvidenceChain,
  AiopsDiagnosticStep,
  DiagnosisResult,
  HypothesisStatus,
  ToolCallAudit
} from "@agent-py/api-contracts";

import AsyncStatusBadge from "./AsyncStatusBadge.vue";
import UserFeedbackControl from "./UserFeedbackControl.vue";

const props = defineProps<{
  readonly chain: AiopsDiagnosticEvidenceChain | null;
  readonly diagnosis?: DiagnosisResult | null;
}>();

const executionSteps = computed(() =>
  [...(props.chain?.steps ?? [])].sort((left, right) => left.sequence - right.sequence)
);

const hypotheses = computed(() => props.diagnosis?.hypotheses ?? []);
const relations = computed(() => props.diagnosis?.hypothesis_relations ?? []);
const conclusion = computed(() => props.diagnosis?.incident_conclusion ?? null);
const assessmentIsStale = computed(() => props.diagnosis?.assessment_is_current === false);
const unassessedCount = computed(() => props.diagnosis?.unassessed_evidence_ids.length ?? 0);

const HYPOTHESIS_STATUS_LABELS: Record<HypothesisStatus, string> = {
  blocked: "受阻",
  contradicted: "已被反驳",
  investigating: "调查中",
  pending: "待验证",
  supported: "有证据支持",
  unresolved: "未决"
};

const STOP_REASON_LABELS: Record<string, string> = {
  budget_exhausted: "调查预算耗尽",
  critical_data_unavailable: "关键数据不可用",
  root_cause_confirmed: "已确认根因"
};

const CONCLUSION_LABELS: Record<string, string> = {
  confirmed: "已确认",
  unconfirmed: "未确认"
};

const NEXT_ACTION_LABELS: Record<string, string> = {
  build_queries: "补充查询",
  finalize: "收敛并生成报告",
  revise_hypotheses: "调整假设"
};

const INVESTIGATION_STATUS_LABELS: Record<string, string> = {
  cancelled: "已取消",
  failed: "调查失败",
  succeeded: "调查完成"
};

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function stringList(value: unknown): readonly string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function modeLabel(value: unknown): string {
  if (value === "mock") return "模拟";
  if (value === "real") return "真实";
  return "未知";
}

function statusLabel(status: string): string {
  return HYPOTHESIS_STATUS_LABELS[status as HypothesisStatus] ?? status;
}

function stopReasonLabel(reason: string): string {
  return STOP_REASON_LABELS[reason] ?? reason;
}

function relationLabel(relationType: string): string {
  if (relationType === "causal_link") return "因果关联";
  if (relationType === "competing") return "竞争解释";
  return relationType;
}

function evidenceRelationLabel(relation: string): string {
  if (relation === "supports") return "支持：";
  if (relation === "contradicts") return "反驳：";
  return "背景：";
}

function statementOf(hypothesisId: string): string {
  const found = hypotheses.value.find((item) => item.hypothesis_id === hypothesisId);
  return found?.statement ?? "已移除的假设";
}

function stepTitle(step: AiopsDiagnosticStep): string {
  const payload = record(step.payload);
  switch (step.phase.toLowerCase()) {
    case "planner": {
      const plan = Array.isArray(payload.plan) ? payload.plan : [];
      return `Planner · 生成 ${plan.length || 1} 步诊断计划`;
    }
    case "executor": {
      const planStep = record(payload.planStep);
      const purpose = typeof planStep.purpose === "string" ? planStep.purpose : "执行诊断步骤";
      return `Executor · ${purpose}`;
    }
    case "replanner": {
      const decision = payload.decision === "executor" ? "调整计划并继续执行" : "证据汇总完成，进入报告";
      return `Replanner · ${decision}`;
    }
    case "evidence_reasoning":
      return "证据推理 · 汇总现场事实";
    case "prepare_context": {
      const tools = Array.isArray(payload.toolNames) ? payload.toolNames.length : 0;
      return `准备上下文 · ${modeLabel(payload.mode)}模式，可用工具 ${tools} 项`;
    }
    case "build_queries": {
      const calls = Array.isArray(payload.calls) ? payload.calls.length : 0;
      return calls > 0 ? `构建查询 · 计划 ${calls} 项查询` : "构建查询 · 本轮无可执行查询";
    }
    case "execute_queries":
      return `执行查询 · 成功 ${number(payload.succeeded)} / 计划 ${number(payload.planned)}`;
    case "revise_hypotheses":
      return payload.initializationFailed === true
        ? "调整假设 · 未能形成有效初始假设"
        : `调整假设 · 新增 ${number(payload.new)}，修改 ${number(payload.revised)}`;
    case "assess_hypotheses": {
      const assessed = Array.isArray(payload.assessed) ? payload.assessed.length : 0;
      const prefix = payload.finalAnalysis === true ? "最终评估" : "评估假设";
      return `${prefix} · 判断 ${assessed} 项，关系 ${number(payload.relations)} 条`;
    }
    case "finalize":
      return `收敛调查 · ${INVESTIGATION_STATUS_LABELS[String(payload.status)] ?? "调查已收尾"}`;
    default:
      return `${step.phase} · ${step.status}`;
  }
}

function stepOutput(step: AiopsDiagnosticStep): readonly string[] {
  const payload = record(step.payload);
  switch (step.phase.toLowerCase()) {
    case "planner": {
      const plan = Array.isArray(payload.plan) ? payload.plan.map(record) : [];
      const lines = plan.slice(0, 5).map((item, index) => {
        const purpose = typeof item.purpose === "string" ? item.purpose : "收集诊断证据";
        const tool = typeof item.tool === "string" ? item.tool : "未指定工具";
        return `${index + 1}. ${purpose}（${tool}）`;
      });
      const evidenceLine = payload.noSopMatched === true
        ? "未命中 SOP，计划退化为通用诊断流程。"
        : "计划已参考可访问的 SOP 或历史案例。";
      return [evidenceLine, ...lines];
    }
    case "executor": {
      const tool = typeof payload.tool === "string" ? payload.tool : "未指定工具";
      return [`调用 ${tool} 收集真实数据。`, `执行状态：${step.status}`];
    }
    case "replanner": {
      const planIndex = typeof payload.planIndex === "number" ? payload.planIndex : 0;
      const planLength = typeof payload.planLength === "number" ? payload.planLength : 0;
      return [
        `计划进度：${planIndex}/${planLength}`,
        payload.executionFailed === true ? "检测到执行失败，停止后续步骤。" : "已根据现有结果完成下一步判断。"
      ];
    }
    case "prepare_context":
      return [
        `可用工具：${stringList(payload.toolNames).join("、") || "无"}`,
        `已装载项目知识服务：${stringList(payload.knowledgeServices).length} 个`
      ];
    case "build_queries": {
      const calls = Array.isArray(payload.calls) ? payload.calls.map(record) : [];
      const lines = calls.slice(0, 5).map((item, index) => {
        const question = typeof item.question === "string" ? item.question : "补充现场证据";
        const tool = typeof item.tool === "string" ? item.tool : "未指定工具";
        return `${index + 1}. ${question}（${tool}）`;
      });
      const unmet = stringList(payload.unmetRequests);
      return [
        ...lines,
        ...unmet.slice(0, 3).map((requirement) => `未满足需求：${requirement}`)
      ];
    }
    case "execute_queries":
      return [
        `计划 ${number(payload.planned)} 项，成功 ${number(payload.succeeded)} 项，失败 ${number(payload.failed)} 项。`
      ];
    case "revise_hypotheses":
      return [
        `新增 ${number(payload.new)} 项假设，修改 ${number(payload.revised)} 项。`,
        ...(payload.initializationFailed === true ? ["现场没有形成可验证的初始假设。"] : [])
      ];
    case "assess_hypotheses": {
      const assessed = Array.isArray(payload.assessed) ? payload.assessed.length : 0;
      return [
        `本次判断 ${assessed} 项假设，形成 ${number(payload.relations)} 条关系。`,
        `事故结论：${CONCLUSION_LABELS[String(payload.conclusion)] ?? "未提供"}`,
        `下一步：${NEXT_ACTION_LABELS[String(payload.nextAction)] ?? "未提供"}`
      ];
    }
    case "finalize":
      return [
        `调查状态：${INVESTIGATION_STATUS_LABELS[String(payload.status)] ?? String(payload.status)}`,
        ...(typeof payload.stopReason === "string" && payload.stopReason.length > 0
          ? [`停止原因：${stopReasonLabel(payload.stopReason)}`]
          : [])
      ];
    default:
      return [`执行状态：${step.status}`];
  }
}

function parseSummary(value: string | null): unknown {
  if (value === null) return null;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return value;
  }
}

function readableLog(recordValue: unknown): string | null {
  const value = record(recordValue);
  const parts: string[] = [];
  for (const key of ["timestamp", "level", "service", "event", "message", "latency_ms"]) {
    const item = value[key];
    if (typeof item === "string" || typeof item === "number") parts.push(String(item));
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

function legacySearchLogRecords(value: unknown): readonly unknown[] {
  if (!Array.isArray(value)) return [];
  for (const item of value) {
    const text = record(item).text;
    if (typeof text !== "string") continue;
    try {
      const logs = JSON.parse(text) as unknown;
      if (!Array.isArray(logs)) continue;
      return logs.map((log) => {
        const rawLog = record(log).LogJson;
        if (typeof rawLog !== "string") return log;
        try {
          return JSON.parse(rawLog) as unknown;
        } catch {
          return {};
        }
      });
    } catch {
      return [];
    }
  }
  return [];
}

function searchLogLines(parsed: unknown): readonly string[] | null {
  const parsedRecord = record(parsed);
  const directRecords = Array.isArray(parsedRecord.records) ? parsedRecord.records : [];
  const records = directRecords.length > 0 ? directRecords : legacySearchLogRecords(parsed);
  if (records.length === 0 && !("recordCount" in parsedRecord)) return null;
  const count = typeof parsedRecord.recordCount === "number" ? parsedRecord.recordCount : records.length;
  const lines = records.slice(0, 5).map(readableLog).filter((line): line is string => line !== null);
  return [
    `共返回 ${count} 条日志${count > 5 ? "，仅展示前 5 条摘要" : ""}。`,
    ...lines
  ];
}

function knowledgeLines(parsed: unknown): readonly string[] | null {
  const parsedRecord = record(parsed);
  const results = Array.isArray(parsedRecord.results) ? parsedRecord.results : null;
  if (results === null) return null;
  const lines = results.slice(0, 5).map((item) => {
    const result = record(item);
    return String(result.source ?? result.title ?? result.documentId ?? "未命名来源");
  });
  return [`命中 ${results.length} 条知识记录。`, ...lines];
}

function genericLines(parsed: unknown): readonly string[] {
  if (parsed === null) return ["工具未返回结果摘要。"];
  if (typeof parsed === "string") {
    if (/^[\[{]/.test(parsed.trim())) return ["工具返回了无法解析的结构化结果，原始数据已隐藏。"];
    return [parsed.length > 500 ? `${parsed.slice(0, 497)}...` : parsed];
  }
  if (Array.isArray(parsed)) return [`工具返回 ${parsed.length} 项结果，原始结构已隐藏。`];
  const parsedRecord = record(parsed);
  const lines = Object.entries(parsedRecord)
    .filter(([, value]) => typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    .slice(0, 6)
    .map(([key, value]) => `${key}：${String(value)}`);
  return lines.length > 0 ? lines : ["工具已返回结构化结果，原始数据已隐藏。"];
}

function toolOutput(tool: ToolCallAudit): readonly string[] {
  if (tool.errorMessage) return [`调用失败：${tool.errorMessage}`];
  const parsed = parseSummary(tool.resultSummary);
  if (tool.toolName === "SearchLog") return searchLogLines(parsed) ?? genericLines(parsed);
  if (tool.toolName === "knowledge_retrieval") return knowledgeLines(parsed) ?? genericLines(parsed);
  return genericLines(parsed);
}
</script>

<template>
  <section class="aiops-execution" aria-label="诊断执行链">
    <button class="aiops-execution__collapse-header" type="button" :aria-expanded="!collapsed" @click="collapsed = !collapsed">
      <div class="aiops-execution__collapse-title">
        <GitBranch :size="16" aria-hidden="true" />
        <div>
          <p>执行链</p>
          <h3>证据、假设与工具调用</h3>
        </div>
      </div>
      <ChevronDown :size="16" class="aiops-execution__collapse-chevron" :class="{ 'aiops-execution__collapse-chevron--open': !collapsed }" aria-hidden="true" />
    </button>

    <div v-show="!collapsed" class="aiops-execution__body">
      <p v-if="chain === null" class="aiops-execution__empty">选择一项诊断，查看持久化执行过程和工具调用。</p>
      <template v-else>
        <section v-if="diagnosis" class="aiops-execution__investigation" aria-label="假设与事故结论">
          <header class="aiops-execution__investigation-header">
            <h4><Lightbulb :size="15" aria-hidden="true" />假设与判断</h4>
            <span v-if="diagnosis.mode === 'mock'" class="aiops-execution__tag aiops-execution__tag--mock">模拟场景</span>
          </header>

          <p v-if="assessmentIsStale" class="aiops-execution__notice">
            以下判断来自此前快照，存在尚未评估的新内容，当前结论尚未完成最新验证。
          </p>
          <p v-if="unassessedCount > 0" class="aiops-execution__notice">
            另有 {{ unassessedCount }} 条证据尚未纳入当前结论。
          </p>

          <div
            v-if="conclusion"
            class="aiops-execution__conclusion"
            :class="{ 'aiops-execution__conclusion--confirmed': conclusion.conclusion_status === 'confirmed' }"
          >
            <strong>{{ conclusion.conclusion_status === "confirmed" ? "事故根因已确认" : "具体根因尚未确认" }}</strong>
            <p v-if="conclusion.conclusion_status === 'confirmed' && conclusion.root_cause">{{ conclusion.root_cause }}</p>
            <p v-if="conclusion.explanation">{{ conclusion.explanation }}</p>
            <p v-if="conclusion.stop_reason" class="aiops-execution__meta-line">停止原因：{{ stopReasonLabel(conclusion.stop_reason) }}</p>
            <p
              v-if="conclusion.conclusion_status === 'unconfirmed' && chain.task.status === 'succeeded'"
              class="aiops-execution__meta-line"
            >
              诊断任务已结束，但事故根因尚未确认，任务终态不代表根因已定。
            </p>
          </div>

          <ul v-if="hypotheses.length" class="aiops-execution__hypotheses">
            <li v-for="item in hypotheses" :key="item.hypothesis_id">
              <div class="aiops-execution__hypothesis-head">
                <strong>{{ item.statement }}</strong>
                <span class="aiops-execution__state" :class="`aiops-execution__state--${item.hypothesis_status}`">{{ statusLabel(item.hypothesis_status) }}</span>
              </div>
              <p v-if="item.assessment" class="aiops-execution__hypothesis-text">{{ item.assessment }}</p>
              <div v-if="item.evidence_links.length" class="aiops-execution__links">
                <p v-for="(link, index) in item.evidence_links" :key="index"><em>{{ evidenceRelationLabel(link.relation) }}</em>{{ link.explanation }}</p>
              </div>
              <div v-if="item.gaps.length" class="aiops-execution__gaps">
                <p v-for="(gap, index) in item.gaps" :key="index">待验证：{{ gap.question }}（{{ gap.why_it_matters }}）</p>
              </div>
            </li>
          </ul>
          <p v-else class="aiops-execution__empty">后端尚未形成任何假设。</p>

          <div v-if="relations.length" class="aiops-execution__relations">
            <h4>假设关系</h4>
            <ul>
              <li v-for="(relation, index) in relations" :key="index">
                <span class="aiops-execution__relation-type">{{ relationLabel(relation.relation_type) }}</span>
                {{ statementOf(relation.from_hypothesis_id) }} → {{ statementOf(relation.to_hypothesis_id) }}：{{ relation.explanation }}
              </li>
            </ul>
          </div>
        </section>

        <ol v-if="executionSteps.length" class="aiops-execution__steps">
          <li v-for="step in executionSteps" :key="step.id">
            <span class="aiops-execution__index">{{ step.sequence }}</span>
            <div>
              <strong>{{ stepTitle(step) }}</strong>
              <div class="aiops-execution__output">
                <p v-for="line in stepOutput(step)" :key="line">{{ line }}</p>
              </div>
              <UserFeedbackControl target-type="diagnostic_step" :target-id="step.id" compact />
            </div>
          </li>
        </ol>
        <p v-else class="aiops-execution__empty">该任务还没有可展示的执行步骤。</p>

        <section class="aiops-execution__tools" aria-label="工具调用">
          <header><h4><Wrench :size="15" aria-hidden="true" />工具调用</h4><span>{{ chain.toolCalls.length }}</span></header>
          <div v-if="chain.toolCalls.length" class="aiops-execution__tool-list">
            <details v-for="tool in chain.toolCalls" :key="tool.id">
              <summary>
                <span><strong>{{ tool.toolName }}</strong><AsyncStatusBadge :status="tool.status" compact /></span>
                <ChevronDown :size="15" aria-hidden="true" />
              </summary>
              <div class="aiops-execution__tool-output">
                <p v-for="line in toolOutput(tool)" :key="line">{{ line }}</p>
              </div>
            </details>
          </div>
          <p v-else class="aiops-execution__empty">该任务没有工具调用。</p>
        </section>
      </template>
    </div>
  </section>
</template>

<style scoped>
.aiops-execution { border-top: 1px solid var(--line); min-width: 0; }
.aiops-execution__collapse-header { align-items: center; background: transparent; border: none; border-bottom: 1px solid transparent; cursor: pointer; display: flex; justify-content: space-between; min-height: 3.75rem; padding: 0 1.2rem; transition: background 0.12s; width: 100%; }
.aiops-execution__collapse-header:hover { background: var(--surface-hover); }
.aiops-execution__collapse-title { align-items: center; display: flex; gap: 0.65rem; }
.aiops-execution__collapse-title p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0 0 0.2rem; text-align: left; }
h3 { font-size: 0.9rem; font-weight: 680; margin: 0; text-align: left; }
h4 { align-items: center; display: flex; font-size: 0.8rem; gap: 0.35rem; margin: 0; }
.aiops-execution__collapse-chevron { color: var(--text-tertiary); flex: 0 0 auto; transition: transform 0.18s; }
.aiops-execution__collapse-chevron--open { transform: rotate(180deg); }
.aiops-execution__body { padding: 1rem 1.2rem 1.2rem; }
.aiops-execution__empty { color: var(--text-tertiary); font-size: 0.78rem; line-height: 1.5; margin: 0; }

.aiops-execution__investigation { border-bottom: 1px solid var(--line); margin-bottom: 1rem; padding-bottom: 1rem; }
.aiops-execution__investigation-header { align-items: center; display: flex; justify-content: space-between; }
.aiops-execution__tag { border: 1px solid var(--line-strong); color: var(--text-tertiary); font-size: 0.68rem; font-weight: 700; padding: 0.12rem 0.45rem; }
.aiops-execution__tag--mock { background: var(--status-running-bg); border-color: var(--status-running-border); color: var(--status-running-text); }
.aiops-execution__notice { background: var(--surface-inset); border-left: 2px solid var(--line-strong); color: var(--text-secondary); font-size: 0.72rem; line-height: 1.55; margin: 0.6rem 0 0; padding: 0.45rem 0.6rem; }
.aiops-execution__conclusion { border: 1px solid var(--line); margin-top: 0.7rem; padding: 0.7rem 0.75rem; }
.aiops-execution__conclusion--confirmed { background: var(--status-success-bg); border-color: var(--status-success-border); }
.aiops-execution__conclusion strong { display: block; font-size: 0.82rem; }
.aiops-execution__conclusion p { color: var(--text-secondary); font-size: 0.74rem; line-height: 1.55; margin: 0.35rem 0 0; overflow-wrap: anywhere; }
.aiops-execution__meta-line { color: var(--text-tertiary) !important; }
.aiops-execution__hypotheses { display: grid; gap: 0.6rem; list-style: none; margin: 0.75rem 0 0; padding: 0; }
.aiops-execution__hypotheses > li { border: 1px solid var(--line); padding: 0.6rem 0.7rem; }
.aiops-execution__hypothesis-head { align-items: flex-start; display: flex; gap: 0.5rem; justify-content: space-between; }
.aiops-execution__hypothesis-head strong { font-size: 0.78rem; line-height: 1.45; overflow-wrap: anywhere; }
.aiops-execution__state { border: 1px solid var(--line-strong); color: var(--text-secondary); flex: 0 0 auto; font-size: 0.66rem; font-weight: 700; padding: 0.1rem 0.4rem; }
.aiops-execution__state--supported { background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text); }
.aiops-execution__state--contradicted { background: var(--status-danger-bg); border-color: var(--status-danger-border); color: var(--status-danger-text); }
.aiops-execution__state--investigating { background: var(--status-running-bg); border-color: var(--status-running-border); color: var(--status-running-text); }
.aiops-execution__hypothesis-text { color: var(--text-secondary); font-size: 0.72rem; line-height: 1.55; margin: 0.4rem 0 0; overflow-wrap: anywhere; }
.aiops-execution__links, .aiops-execution__gaps { border-left: 2px solid var(--line-strong); margin-top: 0.45rem; padding-left: 0.6rem; }
.aiops-execution__links p, .aiops-execution__gaps p { color: var(--text-tertiary); font-size: 0.7rem; line-height: 1.5; margin: 0.2rem 0; overflow-wrap: anywhere; }
.aiops-execution__links em { color: var(--text-secondary); font-style: normal; font-weight: 700; margin-right: 0.2rem; }
.aiops-execution__relations { border-top: 1px solid var(--line); margin-top: 0.8rem; padding-top: 0.7rem; }
.aiops-execution__relations ul { display: grid; gap: 0.4rem; list-style: none; margin: 0.5rem 0 0; padding: 0; }
.aiops-execution__relations li { color: var(--text-secondary); font-size: 0.72rem; line-height: 1.55; overflow-wrap: anywhere; }
.aiops-execution__relation-type { border: 1px solid var(--line-strong); color: var(--text-tertiary); font-size: 0.66rem; font-weight: 700; margin-right: 0.35rem; padding: 0.1rem 0.4rem; }

.aiops-execution__steps { display: grid; gap: 0; list-style: none; margin: 1rem 0 0; padding: 0; }
.aiops-execution__steps li { display: grid; gap: 0.65rem; grid-template-columns: 1.65rem minmax(0, 1fr); padding-bottom: 1rem; position: relative; }
.aiops-execution__steps li:not(:last-child)::after { background: var(--line-strong); content: ""; height: calc(100% - 1.75rem); left: 0.8rem; position: absolute; top: 1.7rem; width: 1px; }
.aiops-execution__index { align-items: center; background: var(--surface-inset); border: 1px solid var(--line-strong); border-radius: 50%; color: var(--text-secondary); display: inline-flex; font-size: 0.68rem; font-weight: 750; height: 1.65rem; justify-content: center; position: relative; width: 1.65rem; z-index: 1; }
.aiops-execution__steps strong { display: block; font-size: 0.8rem; line-height: 1.45; overflow-wrap: anywhere; padding-top: 0.18rem; }
.aiops-execution__output, .aiops-execution__tool-output { border-left: 2px solid var(--line-strong); color: var(--text-secondary); margin-top: 0.5rem; padding: 0.05rem 0 0.05rem 0.7rem; }
.aiops-execution__output p, .aiops-execution__tool-output p { font-size: 0.72rem; line-height: 1.55; margin: 0.22rem 0; overflow-wrap: anywhere; word-break: break-word; }
.aiops-execution__tools { border-top: 1px solid var(--line); margin-top: 0.15rem; padding-top: 1rem; }
.aiops-execution__tools > header { align-items: center; display: flex; justify-content: space-between; }
.aiops-execution__tools h4 { color: var(--text-secondary); }
.aiops-execution__tools > header > span { color: var(--text-tertiary); font-size: 0.72rem; }
.aiops-execution__tool-list { display: grid; gap: 0.45rem; margin-top: 0.75rem; }
.aiops-execution__tool-list details { border-bottom: 1px solid var(--line); padding: 0 0 0.5rem; }
.aiops-execution__tool-list summary { align-items: center; cursor: pointer; display: flex; justify-content: space-between; list-style: none; min-height: 2rem; }
.aiops-execution__tool-list summary::-webkit-details-marker { display: none; }
.aiops-execution__tool-list summary > span { align-items: center; display: flex; gap: 0.5rem; min-width: 0; }
.aiops-execution__tool-list summary strong { font-size: 0.78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aiops-execution__tool-list summary > svg { color: var(--text-tertiary); flex: 0 0 auto; transition: transform var(--transition-fast); }
.aiops-execution__tool-list details[open] summary > svg { transform: rotate(180deg); }
@media (max-width: 560px) { .aiops-execution { padding: 1rem; } }
</style>
