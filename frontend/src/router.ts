import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "dashboard", component: () => import("./views/DashboardView.vue") },
    { path: "/feed", name: "feed", component: () => import("./views/FeedView.vue") },
    { path: "/applications", name: "applications", component: () => import("./views/ApplicationsView.vue") },
    {
      path: "/applications/:id",
      name: "application",
      component: () => import("./views/ApplicationDetailView.vue"),
      props: true,
    },
    { path: "/applications/:id/cover-letter", name: "cover-letter", component: () => import("./views/CoverLetterView.vue"), props: true },
    { path: "/profiles", name: "profiles", component: () => import("./views/ProfilesView.vue") },
    { path: "/me", name: "me", component: () => import("./views/MeView.vue") },
    { path: "/settings", name: "settings", component: () => import("./views/SettingsView.vue") },
  ],
});
