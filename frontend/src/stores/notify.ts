import { defineStore } from "pinia";
import { ref } from "vue";
import { ApiError } from "@/api/client";
import { errorMessage } from "@/i18n";

export interface NotifyAction {
  label: string;
  to: string;
}

/** Global snackbar state. */
export const useNotifyStore = defineStore("notify", () => {
  const message = ref("");
  const visible = ref(false);
  const action = ref<NotifyAction | null>(null);
  const color = ref<"error" | "success" | "warning">("error");

  /** Show the snackbar; red (error) unless a color is given. */
  function show(text: string, c: "error" | "success" | "warning" = "error", a: NotifyAction | null = null) {
    message.value = text;
    action.value = a;
    color.value = c;
    visible.value = true;
  }

  function error(e: unknown) {
    show(e instanceof ApiError ? errorMessage(e) : e instanceof Error ? e.message : String(e));
  }

  return { message, visible, color, action, show, error };
});
