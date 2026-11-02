import {
  createMemoryHistory,
  createRouter,
  createWebHistory,
  type Router
} from "vue-router";

import WorkspaceLayout from "../layouts/WorkspaceLayout.vue";
import AuthView from "../views/AuthView.vue";
import AiopsView from "../views/AiopsView.vue";
import AiopsReportView from "../views/AiopsReportView.vue";
import McpView from "../views/McpView.vue";

export interface AuthRouteAccess {
  initialize(): Promise<void>;
  isAuthenticated(): boolean;
}

export function createAppRouter(auth: AuthRouteAccess): Router {
  const router = createRouter({
    history: typeof window === "undefined" ? createMemoryHistory() : createWebHistory(),
    routes: [
      { path: "/", redirect: "/aiops" },
      {
        path: "/login",
        name: "login",
        component: AuthView,
        props: { mode: "login" },
        meta: { publicOnly: true }
      },
      {
        path: "/register",
        name: "register",
        component: AuthView,
        props: { mode: "register" },
        meta: { publicOnly: true }
      },
      {
        path: "/",
        component: WorkspaceLayout,
        meta: { requiresAuth: true },
        children: [
          {
            path: "aiops",
            name: "aiops",
            component: AiopsView,
            meta: { title: "智能诊断" }
          },
          {
            path: "aiops/reports/:id",
            name: "aiops-report",
            component: AiopsReportView,
            meta: { title: "诊断报告" }
          },
          {
            path: "mcp",
            name: "mcp",
            component: McpView,
            meta: { title: "MCP 连接" }
          }
        ]
      },
      { path: "/:pathMatch(.*)*", redirect: "/aiops" }
    ]
  });

  let initialization: Promise<void> | null = null;
  router.beforeEach(async (to) => {
    initialization ??= auth.initialize();
    await initialization;
    const requiresAuth = to.matched.some((record) => record.meta.requiresAuth === true);
    const publicOnly = to.matched.some((record) => record.meta.publicOnly === true);
    if (requiresAuth && !auth.isAuthenticated()) {
      return { path: "/login", query: { redirect: to.fullPath } };
    }
    if (publicOnly && auth.isAuthenticated()) {
      return { path: "/aiops" };
    }
    return true;
  });

  return router;
}
