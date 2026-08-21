import { createRouter, createWebHistory } from "vue-router";
import LibraryView from "../views/LibraryView.vue";
import EditorView from "../views/EditorView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "library", component: LibraryView },
    { path: "/editor/:id", name: "editor", component: EditorView, props: true },
  ],
});

export default router;
