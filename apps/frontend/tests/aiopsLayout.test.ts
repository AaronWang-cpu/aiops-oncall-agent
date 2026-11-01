import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const aiopsViewSource = readFileSync(
  fileURLToPath(new URL("../src/views/AiopsView.vue", import.meta.url)),
  "utf8"
);
const reportPanelSource = readFileSync(
  fileURLToPath(new URL("../src/components/AiopsReportPanel.vue", import.meta.url)),
  "utf8"
);
const evidenceChainSource = readFileSync(
  fileURLToPath(new URL("../src/components/AiopsEvidenceChain.vue", import.meta.url)),
  "utf8"
);
const timelineSource = readFileSync(
  fileURLToPath(new URL("../src/components/AiopsTimeline.vue", import.meta.url)),
  "utf8"
);

describe("AIOps fixed workspace layout", () => {
  it("constrains the desktop workspace and prevents the console from growing with content", () => {
    expect(aiopsViewSource).toMatch(
      /\.aiops-view\s*\{[^}]*height:\s*100%;[^}]*overflow:\s*hidden;/s
    );
    expect(aiopsViewSource).toMatch(/\.aiops-view__console\s*\{[^}]*overflow:\s*hidden;/s);
    expect(aiopsViewSource).toMatch(
      /\.aiops-view__center\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\) minmax\(8rem, 0\.42fr\);[^}]*overflow:\s*hidden;/s
    );
  });

  it("keeps report metadata fixed and scrolls only the Markdown body", () => {
    expect(reportPanelSource).toMatch(
      /\.aiops-report\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\);[^}]*overflow:\s*hidden;/s
    );
    expect(reportPanelSource).toMatch(
      /\.aiops-report__document\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\) auto;[^}]*overflow:\s*hidden;/s
    );
    expect(reportPanelSource).toMatch(
      /\.aiops-report__document > :deep\(\.markdown-content\)\s*\{[^}]*overflow-y:\s*auto;/s
    );
  });

  it("prevents horizontal page overflow across the diagnosis columns", () => {
    expect(aiopsViewSource).toMatch(
      /\.aiops-view__console\s*\{[^}]*grid-template-columns:\s*minmax\(0, [^)]*\)/s
    );
    expect(aiopsViewSource).toMatch(/\.aiops-view__left\s*\{[^}]*min-width:\s*0;/s);
    expect(aiopsViewSource).toMatch(/\.aiops-view__center\s*\{[^}]*min-width:\s*0;/s);
    expect(aiopsViewSource).toMatch(/\.aiops-view__right\s*\{[^}]*min-width:\s*0;/s);
    expect(aiopsViewSource).toMatch(/@media \(max-width: 1024px\)/);
    expect(aiopsViewSource).toMatch(
      /\.aiops-view__console\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);/s
    );
    expect(evidenceChainSource).toMatch(/\.aiops-execution\s*\{[^}]*min-width:\s*0;/s);
    expect(evidenceChainSource).toMatch(/overflow-wrap:\s*anywhere;/);
    expect(timelineSource).toMatch(/\.aiops-timeline\s*\{[^}]*min-width:\s*0;/s);
    expect(timelineSource).toMatch(/\.aiops-timeline\s*\{[^}]*overflow-x:\s*hidden;/s);
  });
});
