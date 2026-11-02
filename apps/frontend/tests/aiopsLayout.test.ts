import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8");
}

const aiopsViewSource = source("../src/views/AiopsView.vue");
const reportPanelSource = source("../src/components/AiopsReportPanel.vue");
const executionChainSource = source("../src/components/AiopsExecutionChain.vue");
const evidencePanelSource = source("../src/components/AiopsEvidencePanel.vue");
const timelineSource = source("../src/components/AiopsTimeline.vue");

describe("AIOps workbench layout", () => {
  it("keeps the alert list and the diagnosis column inside one viewport", () => {
    expect(aiopsViewSource).toMatch(
      /\.aiops-workbench\s*\{[^}]*grid-template-columns:\s*minmax\(16rem, 19rem\) minmax\(0, 1fr\);[^}]*height:\s*100%;[^}]*overflow:\s*hidden;/s
    );
    expect(aiopsViewSource).toMatch(
      /\.aiops-workbench__primary\s*\{[^}]*display:\s*flex;[^}]*overflow-y:\s*auto;/s
    );
  });

  it("scrolls each column on its own and stacks them on narrow screens", () => {
    expect(aiopsViewSource).toMatch(/\.aiops-workbench__sources\s*\{[^}]*min-width:\s*0;[^}]*overflow-y:\s*auto;/s);
    expect(aiopsViewSource).toMatch(/@media \(max-width: 1024px\)/);
    expect(aiopsViewSource).toMatch(
      /@media \(max-width: 1024px\)\s*\{\s*\.aiops-workbench\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);[^}]*height:\s*auto;[^}]*overflow:\s*visible;/s
    );
  });

  it("keeps long content inside the reading surfaces", () => {
    expect(reportPanelSource).toMatch(/\.aiops-report\s*\{[^}]*min-width:\s*0;[^}]*overflow:\s*hidden;/s);
    expect(reportPanelSource).toMatch(
      /\.aiops-report__document > :deep\(\.markdown-content\)\s*\{[^}]*overflow-y:\s*auto;/s
    );
    expect(executionChainSource).toMatch(/\.aiops-execution\s*\{[^}]*min-width:\s*0;/s);
    expect(executionChainSource).toMatch(/overflow-wrap:\s*anywhere;/);
    expect(timelineSource).toMatch(/\.aiops-timeline\s*\{[^}]*min-width:\s*0;/s);
    expect(timelineSource).toMatch(/\.aiops-timeline\s*\{[^}]*overflow-x:\s*hidden;/s);
  });

  it("gives the evidence inspector a scrolling surface of its own", () => {
    expect(evidencePanelSource).toMatch(/\.aiops-evidence\s*\{[^}]*min-width:\s*0;/s);
    expect(evidencePanelSource).toMatch(/overflow-wrap:\s*anywhere;/);
  });
});
