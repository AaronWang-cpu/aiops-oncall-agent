import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";

import { createAppRouter } from "../src/router";
import { useFeedbackStore } from "../src/stores/feedback";

describe("application shell router", () => {
  it("redirects anonymous visitors to sign in and preserves the target route", async () => {
    const router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => false
    });

    await router.push("/aiops");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.currentRoute.value.query.redirect).toBe("/aiops");
  });

  it("redirects authenticated visitors away from public auth routes", async () => {
    const router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => true
    });

    await router.push("/register");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/aiops");
  });

  it("sends unknown paths to the diagnosis workspace", async () => {
    const router = createAppRouter({
      initialize: vi.fn().mockResolvedValue(undefined),
      isAuthenticated: () => true
    });

    await router.push("/retired-section");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/aiops");
  });

  it("holds dismissible normalized feedback in application state", () => {
    setActivePinia(createPinia());
    const feedback = useFeedbackStore();

    feedback.showError("The system is temporarily unavailable.");
    expect(feedback.current?.message).toBe("The system is temporarily unavailable.");

    feedback.dismiss();
    expect(feedback.current).toBeNull();
  });
});
