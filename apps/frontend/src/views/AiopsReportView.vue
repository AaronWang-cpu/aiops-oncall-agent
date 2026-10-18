<script setup lang="ts">
import { ArrowLeft, Download, FileWarning } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppLoadingState from "../components/AppLoadingState.vue";
import MarkdownContent from "../components/MarkdownContent.vue";
import UserFeedbackControl from "../components/UserFeedbackControl.vue";
import { createAiopsClient } from "../aiops/aiopsClient";

const route = useRoute();
const router = useRouter();
const client = createAiopsClient();

interface ReportDisplay {
  readonly id: string;
  readonly title: string;
  readonly content: string;
  readonly createdAt: string | null;
  readonly taskQuery: string;
}

const report = ref<ReportDisplay | null>(null);
const isLoading = ref(true);
const errorMessage = ref<string | null>(null);

const diagnosticId = computed(() => {
  const id = route.params["id"];
  return typeof id === "string" ? id : null;
});

onMounted(async () => {
  const id = diagnosticId.value;
  if (id === null) {
    errorMessage.value = "无效的报告链接。";
    isLoading.value = false;
    return;
  }
  try {
    const chain = await client.getEvidenceChain(id);
    const reports = chain.reports ?? [];
    const last = reports[reports.length - 1];
    if (last === undefined) {
      errorMessage.value = "该诊断任务尚未生成报告。";
    } else {
      report.value = {
        id: last.id,
        title: last.title,
        content: last.content,
        createdAt: last.createdAt,
        taskQuery: chain.task.query
      };
    }
  } catch {
    errorMessage.value = "无法加载报告，请确认诊断任务 ID 有效。";
  } finally {
    isLoading.value = false;
  }
});

function downloadReport(): void {
  const r = report.value;
  if (r === null) return;
  const blob = new Blob([r.content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const ts = r.createdAt
    ? new Date(r.createdAt).toISOString().slice(0, 19).replace(/[T:]/g, "-")
    : "report";
  a.href = url;
  a.download = `aiops-report-${ts}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

function goBack(): void {
  void router.push({ name: "aiops" });
}
</script>

<template>
  <section class="report-view" aria-label="诊断报告详情">
    <header class="report-view__header">
      <button class="report-view__back" type="button" @click="goBack">
        <ArrowLeft :size="16" aria-hidden="true" />返回诊断
      </button>
      <div class="report-view__title-area">
        <p>诊断报告</p>
        <h2 v-if="report">{{ report.title }}</h2>
        <h2 v-else-if="!isLoading">报告</h2>
      </div>
      <button v-if="report" class="report-view__download" type="button" @click="downloadReport">
        <Download :size="15" aria-hidden="true" />下载 Markdown
      </button>
    </header>

    <AppLoadingState v-if="isLoading" label="正在加载报告" />

    <div v-else-if="errorMessage" class="report-view__error">
      <FileWarning :size="32" aria-hidden="true" />
      <strong>{{ errorMessage }}</strong>
      <button type="button" @click="goBack">返回诊断工作区</button>
    </div>

    <article v-else-if="report" class="report-view__body">
      <div class="report-view__meta">
        <span class="report-view__query">{{ report.taskQuery }}</span>
        <time v-if="report.createdAt" :datetime="report.createdAt">
          {{ new Date(report.createdAt).toLocaleString("zh-CN") }}
        </time>
      </div>
      <MarkdownContent :content="report.content" mode="report" />
      <footer class="report-view__footer">
        <UserFeedbackControl target-type="diagnostic_report" :target-id="report.id" />
      </footer>
    </article>
  </section>
</template>

<style scoped>
.report-view { background: var(--surface-raised); display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
.report-view__header { align-items: center; border-bottom: 1px solid var(--line); display: grid; gap: 0.9rem; grid-template-columns: auto minmax(0, 1fr) auto; min-height: 4.6rem; padding: 0.85rem clamp(1rem, 2.6vw, 1.8rem); }
.report-view__back { align-items: center; background: var(--surface); border: 1px solid var(--line-strong); color: var(--text-secondary); cursor: pointer; display: inline-flex; font-size: 0.8rem; font-weight: 650; gap: 0.4rem; min-height: 2.2rem; padding: 0.3rem 0.85rem; transition: background 0.12s, color 0.12s; white-space: nowrap; }
.report-view__back:hover { background: var(--surface-raised); color: var(--text-primary); }
.report-view__title-area { min-width: 0; }
.report-view__title-area p { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 760; margin: 0 0 0.22rem; }
.report-view__title-area h2 { font-size: clamp(0.98rem, 1.2vw, 1.15rem); font-weight: 720; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.report-view__download { align-items: center; background: var(--surface); border: 1px solid var(--line-strong); color: var(--text-secondary); cursor: pointer; display: inline-flex; font-size: 0.8rem; font-weight: 650; gap: 0.4rem; min-height: 2.2rem; padding: 0.3rem 0.85rem; transition: background 0.12s, color 0.12s; white-space: nowrap; }
.report-view__download:hover { background: var(--surface-raised); color: var(--text-primary); }
.report-view__error { align-items: center; color: var(--text-tertiary); display: flex; flex-direction: column; gap: 1rem; justify-content: center; padding: 4rem 2rem; }
.report-view__error strong { color: var(--text-secondary); font-size: 0.95rem; }
.report-view__error button { background: var(--surface); border: 1px solid var(--line-strong); color: var(--text-secondary); cursor: pointer; font-size: 0.82rem; min-height: 2.2rem; padding: 0.3rem 1rem; }
.report-view__body { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; min-height: 0; overflow: hidden; }
.report-view__meta { align-items: baseline; border-bottom: 1px solid var(--line); display: flex; gap: 1rem; justify-content: space-between; padding: 0.75rem clamp(1rem, 2.6vw, 1.8rem); }
.report-view__query { color: var(--text-secondary); font-size: 0.82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.report-view__meta time { color: var(--text-tertiary); flex-shrink: 0; font-size: 0.72rem; white-space: nowrap; }
.report-view__body > :deep(.markdown-content) { overflow-y: auto; overscroll-behavior: contain; padding: clamp(1.5rem, 4vw, 3rem) clamp(1rem, 4vw, 4rem); }
.report-view__footer { border-top: 1px solid var(--line); padding: 0.75rem clamp(1rem, 2.6vw, 1.8rem); }
@media (max-width: 860px) { .report-view__header { grid-template-columns: auto minmax(0, 1fr); } .report-view__download { grid-column: 1 / -1; justify-self: start; } .report-view__meta { align-items: flex-start; flex-direction: column; } }
</style>
