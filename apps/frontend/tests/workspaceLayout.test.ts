import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const workspaceSource = readFileSync(
  fileURLToPath(new URL("../src/layouts/WorkspaceLayout.vue", import.meta.url)),
  "utf8"
);
const aiopsSource = readFileSync(
  fileURLToPath(new URL("../src/views/AiopsView.vue", import.meta.url)),
  "utf8"
);

describe("edge-to-edge desktop workspace", () => {
  it("removes the centered max-width and outer padding from routed content", () => {
    expect(workspaceSource).toMatch(
      /\.workspace-layout__main\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\);[^}]*height:\s*100dvh;/s
    );
    expect(workspaceSource).toMatch(
      /\.workspace-layout__content\s*\{ height:\s*100%; min-height:\s*0; overflow:\s*hidden; width:\s*100%; \}/
    );
    expect(workspaceSource).not.toMatch(/\.workspace-layout__content\s*\{[^}]*max-width:/s);
  });

  it("lets the diagnosis workspace own the full routed surface", () => {
    expect(aiopsSource).toMatch(/\.aiops-view\s*\{[^}]*height:\s*100%;[^}]*overflow:\s*hidden;/s);
    expect(aiopsSource).not.toMatch(/\.aiops-view\s*\{[^}]*border-radius:/s);
  });

  it("keeps only the diagnosis and connection sections in the rail navigation", () => {
    const navigationSource = readFileSync(
      fileURLToPath(new URL("../src/components/WorkspaceNavigation.vue", import.meta.url)),
      "utf8"
    );

    expect(navigationSource).toContain('label: "智能诊断", to: "/aiops"');
    expect(navigationSource).toContain('label: "MCP 连接", to: "/mcp"');
    expect(navigationSource).not.toContain('"/chat"');
    expect(navigationSource).not.toContain('"/knowledge"');
  });
});
