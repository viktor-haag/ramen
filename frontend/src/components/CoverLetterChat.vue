<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { CoverLetterMessage } from "@/api/types";

/** Mirrors the backend limit for one chat message. */
const MESSAGE_MAX = 2000;

const props = defineProps<{
  messages: CoverLetterMessage[];
  disabled?: boolean;
  hint?: string | null;
  /** Sends the text; resolves true when it was accepted (the field is then cleared). */
  submit: (text: string) => Promise<boolean>;
}>();

const { t } = useI18n();
const text = ref("");
const sending = ref(false);
const list = ref<HTMLElement | null>(null);

const tooLong = computed(() => text.value.length > MESSAGE_MAX);
const canSend = computed(() => !props.disabled && !sending.value && !tooLong.value && text.value.trim() !== "");

async function send() {
  if (!canSend.value) return;
  sending.value = true;
  try {
    if (await props.submit(text.value.trim())) text.value = "";
  } finally {
    sending.value = false;
  }
}

/** Enter sends, Shift+Enter inserts a line break. */
function onKeydown(e: KeyboardEvent) {
  // keyCode 229: Safari reports IME composition this way
  if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229) return;
  e.preventDefault();
  void send();
}

watch(
  () => props.messages.length,
  async () => {
    await nextTick();
    if (list.value) list.value.scrollTop = list.value.scrollHeight;
  },
  { immediate: true },
);
</script>

<template>
  <div class="cl-chat d-flex flex-column ga-2" data-test="cl-chat">
    <div class="text-subtitle-1">{{ t("coverLetter.chat.title") }}</div>
    <div ref="list" class="cl-chat-list d-flex flex-column ga-2" data-test="cl-chat-list">
      <div v-if="!messages.length" class="text-body-2 text-medium-emphasis">{{ t("coverLetter.chat.empty") }}</div>
      <div
        v-for="m in messages"
        :key="m.id"
        :class="['cl-msg', 'text-body-2', m.role === 'user' ? 'cl-msg-user align-self-end' : 'cl-msg-assistant align-self-start']"
        :data-test="`cl-msg-${m.role}`"
      >
        {{ m.text }}
      </div>
    </div>
    <div v-if="hint" class="text-caption text-medium-emphasis" data-test="cl-chat-hint">{{ hint }}</div>
    <v-textarea
      v-model="text"
      :placeholder="t('coverLetter.chat.placeholder')"
      :counter="MESSAGE_MAX"
      :error="tooLong"
      :disabled="disabled"
      rows="2"
      max-rows="6"
      auto-grow
      density="comfortable"
      data-test="cl-chat-input"
      @keydown="onKeydown"
    />
    <div class="d-flex">
      <v-spacer />
      <v-btn color="primary" variant="flat" prepend-icon="mdi-send" :disabled="!canSend" :loading="sending" data-test="cl-chat-send" @click="send">
        {{ t("coverLetter.chat.send") }}
      </v-btn>
    </div>
  </div>
</template>

<style scoped>
.cl-chat-list {
  max-height: 50vh;
  overflow-y: auto;
}
.cl-msg {
  max-width: 85%;
  padding: 8px 12px;
  border-radius: 12px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.cl-msg-user {
  background: rgb(var(--v-theme-primary));
  color: rgb(var(--v-theme-on-primary));
}
.cl-msg-assistant {
  background: rgb(var(--v-theme-surface-light));
}
</style>
