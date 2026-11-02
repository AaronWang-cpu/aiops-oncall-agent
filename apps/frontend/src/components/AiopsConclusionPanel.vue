<script setup lang="ts">
import { Lightbulb } from "lucide-vue-next";
import { computed } from "vue";

import type { DiagnosisResult, HypothesisStatus } from "@agent-py/api-contracts";

const props = defineProps<{
  readonly diagnosis: DiagnosisResult | null;
  readonly taskStatus: string | null;
}>();

const emit = defineEmits<{ "open-evidence": [evidenceId: string] }>();

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

const conclusion = computed(() => props.diagnosis?.incident_conclusion ?? null);
const hypotheses = computed(() => props.diagnosis?.hypotheses ?? []);
const relations = computed(() => props.diagnosis?.hypothesis_relations ?? []);
const assessmentIsStale = computed(() => props.diagnosis?.assessment_is_current === false);
const unassessedCount = computed(() => props.diagnosis?.unassessed_evidence_ids.length ?? 0);

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
  if (relation === "supports") return "支持";
  if (relation === "contradicts") return "反驳";
  return "背景";
}

function statementOf(hypothesisId: string): string {
  const found = hypotheses.value.find((item) => item.hypothesis_id === hypothesisId);
  return found?.statement ?? "已移除的假设";
}
</script>

<template>
  <section class="aiops-conclusion" aria-label="事故结论与假设">
    <header>
      <h4><Lightbulb :size="15" aria-hidden="true" />事故结论</h4>
      <span v-if="diagnosis?.mode === 'mock'" class="aiops-conclusion__tag">模拟场景</span>
    </header>

    <p v-if="diagnosis === null" class="aiops-conclusion__empty">选择或发起一次诊断后，这里显示结论与假设。</p>
    <template v-else>
      <p v-if="assessmentIsStale" class="aiops-conclusion__notice">
        以下判断来自此前快照，存在尚未评估的新内容，当前结论尚未完成最新验证。
      </p>
      <p v-if="unassessedCount > 0" class="aiops-conclusion__notice">
        另有 {{ unassessedCount }} 条证据尚未纳入当前结论。
      </p>

      <div
        v-if="conclusion"
        class="aiops-conclusion__verdict"
        :class="{ 'aiops-conclusion__verdict--confirmed': conclusion.conclusion_status === 'confirmed' }"
      >
        <strong>{{ conclusion.conclusion_status === "confirmed" ? "事故根因已确认" : "具体根因尚未确认" }}</strong>
        <p v-if="conclusion.conclusion_status === 'confirmed' && conclusion.root_cause">{{ conclusion.root_cause }}</p>
        <p v-if="conclusion.explanation">{{ conclusion.explanation }}</p>
        <p v-if="conclusion.stop_reason" class="aiops-conclusion__meta">停止原因：{{ stopReasonLabel(conclusion.stop_reason) }}</p>
        <p v-if="conclusion.conclusion_status === 'unconfirmed' && taskStatus === 'succeeded'" class="aiops-conclusion__meta">
          诊断任务已结束，但事故根因尚未确认，任务终态不代表根因已定。
        </p>
      </div>

      <h4 class="aiops-conclusion__section-title">假设与判断</h4>
      <ul v-if="hypotheses.length" class="aiops-conclusion__hypotheses">
        <li v-for="item in hypotheses" :key="item.hypothesis_id">
          <div class="aiops-conclusion__hypothesis-head">
            <strong>{{ item.statement }}</strong>
            <span class="aiops-conclusion__state" :class="`aiops-conclusion__state--${item.hypothesis_status}`">{{ statusLabel(item.hypothesis_status) }}</span>
          </div>
          <p v-if="item.assessment" class="aiops-conclusion__text">{{ item.assessment }}</p>
          <ul v-if="item.evidence_links.length" class="aiops-conclusion__links">
            <li v-for="(link, index) in item.evidence_links" :key="index">
              <em>{{ evidenceRelationLabel(link.relation) }}</em>
              <button type="button" :title="`查看证据 ${link.evidence_id}`" @click="emit('open-evidence', link.evidence_id)">{{ link.evidence_id }}</button>
              <span>{{ link.explanation }}</span>
            </li>
          </ul>
          <ul v-if="item.gaps.length" class="aiops-conclusion__gaps">
            <li v-for="(gap, index) in item.gaps" :key="index">待验证：{{ gap.question }}（{{ gap.why_it_matters }}）</li>
          </ul>
        </li>
      </ul>
      <p v-else class="aiops-conclusion__empty">后端尚未形成任何假设。</p>

      <div v-if="relations.length" class="aiops-conclusion__relations">
        <h4 class="aiops-conclusion__section-title">假设关系</h4>
        <ul>
          <li v-for="(relation, index) in relations" :key="index">
            <span class="aiops-conclusion__relation-type">{{ relationLabel(relation.relation_type) }}</span>
            {{ statementOf(relation.from_hypothesis_id) }} → {{ statementOf(relation.to_hypothesis_id) }}：{{ relation.explanation }}
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style scoped>
.aiops-conclusion { display: grid; gap: 0.7rem; min-width: 0; }
header { align-items: center; display: flex; justify-content: space-between; }
h4 { align-items: center; display: flex; font-size: 0.82rem; gap: 0.35rem; margin: 0; }
.aiops-conclusion__section-title { border-top: 1px solid var(--line); color: var(--text-secondary); padding-top: 0.7rem; }
.aiops-conclusion__tag { border: 1px solid var(--line-strong); color: var(--text-tertiary); font-size: 0.68rem; font-weight: 700; padding: 0.1rem 0.4rem; }
.aiops-conclusion__notice { background: var(--status-warning-bg, rgb(255 247 224)); border: 1px solid var(--line-strong); color: var(--text-secondary); font-size: 0.74rem; line-height: 1.5; margin: 0; padding: 0.45rem 0.55rem; }
.aiops-conclusion__verdict { border: 1px solid var(--line); display: grid; gap: 0.3rem; padding: 0.65rem 0.7rem; }
.aiops-conclusion__verdict--confirmed { border-color: var(--status-success-text); }
.aiops-conclusion__verdict strong { font-size: 0.84rem; }
.aiops-conclusion__verdict p { font-size: 0.78rem; line-height: 1.55; margin: 0; overflow-wrap: anywhere; }
.aiops-conclusion__meta { color: var(--text-tertiary); font-size: 0.74rem !important; }
.aiops-conclusion__empty { color: var(--text-tertiary); font-size: 0.78rem; line-height: 1.5; margin: 0; }
.aiops-conclusion__hypotheses { display: grid; gap: 0.75rem; list-style: none; margin: 0; padding: 0; }
.aiops-conclusion__hypotheses > li { border-left: 2px solid var(--line-strong); display: grid; gap: 0.3rem; padding-left: 0.6rem; }
.aiops-conclusion__hypothesis-head { align-items: start; display: flex; gap: 0.5rem; justify-content: space-between; }
.aiops-conclusion__hypothesis-head strong { font-size: 0.8rem; line-height: 1.4; overflow-wrap: anywhere; }
.aiops-conclusion__state { border: 1px solid var(--line-strong); color: var(--text-secondary); flex: 0 0 auto; font-size: 0.68rem; font-weight: 700; padding: 0.05rem 0.35rem; }
.aiops-conclusion__state--supported { border-color: var(--status-success-text); color: var(--status-success-text); }
.aiops-conclusion__state--contradicted { border-color: var(--status-danger-text); color: var(--status-danger-text); }
.aiops-conclusion__text { font-size: 0.78rem; line-height: 1.55; margin: 0; overflow-wrap: anywhere; }
.aiops-conclusion__links, .aiops-conclusion__gaps { display: grid; gap: 0.25rem; list-style: none; margin: 0; padding: 0; }
.aiops-conclusion__links li { align-items: baseline; display: flex; flex-wrap: wrap; font-size: 0.74rem; gap: 0.35rem; line-height: 1.5; overflow-wrap: anywhere; }
.aiops-conclusion__links em { color: var(--text-secondary); font-style: normal; font-weight: 650; }
.aiops-conclusion__links button { background: transparent; border: 1px dashed var(--line-strong); color: var(--accent-strong); cursor: pointer; font-family: inherit; font-size: 0.72rem; padding: 0.05rem 0.3rem; }
.aiops-conclusion__links button:hover { background: var(--surface-hover); }
.aiops-conclusion__gaps li { color: var(--text-tertiary); font-size: 0.74rem; line-height: 1.5; overflow-wrap: anywhere; }
.aiops-conclusion__relations ul { display: grid; gap: 0.3rem; list-style: none; margin: 0.5rem 0 0; padding: 0; }
.aiops-conclusion__relations li { font-size: 0.76rem; line-height: 1.55; overflow-wrap: anywhere; }
.aiops-conclusion__relation-type { color: var(--accent-strong); font-weight: 700; margin-right: 0.25rem; }
</style>
