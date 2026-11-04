<script setup lang="ts">
import { ChevronDown, GitBranch, Wrench } from "lucide-vue-next";
import { computed, ref } from "vue";

import type { AiopsDiagnosticEvidenceChain, AiopsDiagnosticStep, ToolCallAudit } from "@agent-py/api-contracts";

import AsyncStatusBadge from "./AsyncStatusBadge.vue";

const props = defineProps<{ readonly chain: AiopsDiagnosticEvidenceChain | null }>();
const emit = defineEmits<{ "open-evidence": [evidenceId: string] }>();

const collapsed = ref(false);

const executionSteps = computed(() =>
  [...(props.chain?.steps ?? [])].sort((left, right) => left.sequence - right.sequence)
);

const CONCLUSION_LABELS: Record<string, string> = {
  confirmed: "已确认",
  unconfirmed: "未确认"
};

const INVESTIGATION_STATUS_LABELS: Record<string, string> = {
  cancelled: "已取消",
  failed: "调查失败",
  succeeded: "调查完成"
};

const NEXT_ACTION_LABELS: Record<string, string> = {
  build_queries: "补充查询",
  finalize: "收敛并生成报告",
  revise_hypotheses: "调整假设"
};

const STOP_REASON_LABELS: Record<string, string> = {
  budget_exhausted: "调查预算耗尽",
  critical_data_unavailable: "关键数据不可用",
  root_cause_confirmed: "已确认根因"
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

function stopReasonLabel(reason: string): string {
  return STOP_REASON_LABELS[reason] ?? reason;
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

function evidenceOf(tool: ToolCallAudit): readonly { readonly id: string; readonly summary: string; readonly kind: string }[] {
  return (props.chain?.evidence ?? [])
    .filter((item) => item.toolCallId === tool.id)
    .map((item) => ({ id: item.id, kind: item.kind, summary: item.summary }));
}

function durationText(tool: ToolCallAudit): string {
  return tool.durationMs === null ? "耗时未记录" : `耗时 ${tool.durationMs} ms`;
}
</script>

<template>
  <section class="aiops-execution" aria-label="诊断执行链">
    <button class="aiops-execution__header" type="button" :aria-expanded="!collapsed" @click="collapsed = !collapsed">
      <GitBranch :size="15" aria-hidden="true" />
      <span>执行链</span>
      <small>{{ executionSteps.length }} 步 / {{ chain?.toolCalls.length ?? 0 }} 次调用</small>
    </button>

    <div v-show="!collapsed" class="aiops-execution__body">
      <p v-if="chain === null" class="aiops-execution__empty">选择一项诊断，查看持久化的节点步骤与工具调用。</p>
      <template v-else>
        <ol v-if="executionSteps.length" class="aiops-execution__steps">
          <li v-for="step in executionSteps" :key="step.id">
            <span class="aiops-execution__index">{{ step.sequence }}</span>
            <div>
              <div class="aiops-execution__step-head">
                <strong>{{ stepTitle(step) }}</strong>
                <AsyncStatusBadge :status="step.status" compact />
              </div>
              <p v-for="line in stepOutput(step)" :key="line">{{ line }}</p>
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
                <p>{{ durationText(tool) }}</p>
                <p v-if="tool.errorMessage" class="aiops-execution__tool-error">调用失败：{{ tool.errorMessage }}</p>
                <template v-if="evidenceOf(tool).length">
                  <p>本次调用写入的证据：</p>
                  <ul>
                    <li v-for="item in evidenceOf(tool)" :key="item.id">
                      <button type="button" :aria-label="`查看证据 ${item.id}`" @click="emit('open-evidence', item.id)">
                        [{{ item.kind }}] {{ item.summary || item.id }}
                      </button>
                    </li>
                  </ul>
                </template>
                <p v-else-if="!tool.errorMessage">本次调用没有写入证据。</p>
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
.aiops-execution__header { align-items: center; background: transparent; border: none; cursor: pointer; display: flex; gap: 0.45rem; min-height: 2.9rem; padding: 0 1.2rem; text-align: left; width: 100%; }
.aiops-execution__header:hover { background: var(--surface-hover); }
.aiops-execution__header span { font-size: 0.82rem; font-weight: 680; }
.aiops-execution__header small { color: var(--text-tertiary); font-size: 0.7rem; margin-left: auto; }
.aiops-execution__body { display: grid; gap: 1rem; padding: 0.2rem 1.2rem 1.2rem; }
.aiops-execution__empty { color: var(--text-tertiary); font-size: 0.78rem; line-height: 1.5; margin: 0; }
.aiops-execution__steps { display: grid; gap: 0.75rem; list-style: none; margin: 0; padding: 0; }
.aiops-execution__steps > li { display: grid; gap: 0.6rem; grid-template-columns: 1.5rem minmax(0, 1fr); }
.aiops-execution__index { background: var(--surface-hover); border: 1px solid var(--line); color: var(--text-secondary); font-size: 0.7rem; font-weight: 700; height: 1.4rem; line-height: 1.4rem; text-align: center; }
.aiops-execution__steps > li > div { display: grid; gap: 0.2rem; min-width: 0; }
.aiops-execution__step-head { align-items: center; display: flex; flex-wrap: wrap; gap: 0.45rem; }
.aiops-execution__step-head strong { font-size: 0.79rem; line-height: 1.45; overflow-wrap: anywhere; }
.aiops-execution__steps p { color: var(--text-secondary); font-size: 0.75rem; line-height: 1.5; margin: 0; overflow-wrap: anywhere; }
.aiops-execution__tools { border-top: 1px solid var(--line); padding-top: 0.8rem; }
.aiops-execution__tools > header { align-items: center; display: flex; justify-content: space-between; }
.aiops-execution__tools > header span { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 650; }
h4 { align-items: center; display: flex; font-size: 0.8rem; gap: 0.35rem; margin: 0; }
.aiops-execution__tool-list { display: grid; gap: 0.35rem; margin-top: 0.6rem; }
details { border: 1px solid var(--line); min-width: 0; }
summary { align-items: center; cursor: pointer; display: flex; font-size: 0.78rem; gap: 0.4rem; justify-content: space-between; padding: 0.45rem 0.55rem; }
summary > span { align-items: center; display: flex; gap: 0.4rem; min-width: 0; }
summary strong { overflow-wrap: anywhere; }
.aiops-execution__tool-output { border-top: 1px solid var(--line); display: grid; gap: 0.3rem; padding: 0.5rem 0.55rem; }
.aiops-execution__tool-output p { color: var(--text-secondary); font-size: 0.75rem; line-height: 1.5; margin: 0; overflow-wrap: anywhere; }
.aiops-execution__tool-error { color: var(--status-danger-text) !important; }
.aiops-execution__tool-output ul { display: grid; gap: 0.25rem; list-style: none; margin: 0; padding: 0; }
.aiops-execution__tool-output button { background: transparent; border: 1px dashed var(--line-strong); color: var(--accent-strong); cursor: pointer; font-family: inherit; font-size: 0.74rem; overflow-wrap: anywhere; padding: 0.25rem 0.4rem; text-align: left; width: 100%; }
.aiops-execution__tool-output button:hover { background: var(--surface-hover); }
</style>
