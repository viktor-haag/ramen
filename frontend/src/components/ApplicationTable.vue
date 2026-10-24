<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { formatDate } from "@/domain/time";
import ApplicationContextMenu from "@/components/ApplicationContextMenu.vue";
import { useLongPress } from "@/composables/useLongPress";
import type { ApplicationOut } from "@/api/types";
import { useApplicationsStore } from "@/stores/applications";

const { t, locale } = useI18n();
const router = useRouter();
const store = useApplicationsStore();

const search = ref<string | null>(store.q);
let timer: ReturnType<typeof setTimeout> | undefined;
watch(search, (v) => {
  clearTimeout(timer);
  timer = setTimeout(() => {
    const next = (v ?? "").trim();
    if (next === (store.q ?? "").trim()) return;
    store.q = next;
    void store.load();
  }, 300);
});
onBeforeUnmount(() => clearTimeout(timer));

function onRow(_e: unknown, { item }: { item: { id: number } }) {
  void router.push("/applications/" + item.id);
}

const menu = ref({ open: false, x: 0, y: 0, app: null as ApplicationOut | null });

function openMenu(e: MouseEvent, id: number) {
  const app = store.items.find((a) => a.id === id);
  if (app) menu.value = { open: true, x: e.clientX, y: e.clientY, app };
}

function onRowContextmenu(e: MouseEvent, { item }: { item: { id: number } }) {
  e.preventDefault();
  openMenu(e, item.id);
}

const longPress = useLongPress((e) => {
  const id = Number((e.target as HTMLElement | null)?.closest<HTMLElement>("tr[data-id]")?.dataset.id);
  if (Number.isFinite(id)) openMenu(e, id);
});

function rowProps({ item }: { item: { id: number } }) {
  return {
    "data-id": item.id,
    onPointerdown: longPress.onPointerdown,
    onPointermove: longPress.onPointermove,
    onPointerup: longPress.onPointerup,
    onPointercancel: longPress.onPointercancel,
    onPointerleave: longPress.onPointerleave,
    onClickCapture: longPress.onClickCapture,
  };
}

const headers = computed(() => [
  { title: t("applications.columns.title"), key: "title" },
  { title: t("applications.columns.company"), key: "company" },
  { title: t("applications.columns.location"), key: "location" },
  { title: t("applications.columns.status"), key: "statusLabel" },
  { title: t("applications.columns.lastChange"), key: "lastChange" },
  { title: t("applications.columns.created"), key: "created" },
]);

const rows = computed(() =>
  store.visibleItems.map((a) => ({
    id: a.id,
    title: a.posting.title ?? "",
    company: a.posting.company ?? "",
    location: a.posting.location ?? "",
    statusLabel: t(`status.${a.status}`),
    lastChange: a.last_status_change_at ?? a.created_at,
    created: a.created_at,
  })),
);
</script>

<template>
  <v-text-field
    v-model="search"
    :label="t('applications.search')"
    prepend-inner-icon="mdi-magnify"
    clearable
    hide-details
    density="compact"
    class="mb-3"
    style="max-width: 360px"
  />
  <v-data-table
    :headers="headers"
    :items="rows"
    :loading="store.loading"
    hover
    :row-props="rowProps"
    @click:row="onRow"
    @contextmenu:row="onRowContextmenu"
  >
    <template #item.lastChange="{ item }">{{ formatDate(item.lastChange, locale) }}</template>
    <template #item.created="{ item }">{{ formatDate(item.created, locale) }}</template>
  </v-data-table>
  <ApplicationContextMenu v-model="menu.open" :application="menu.app" :x="menu.x" :y="menu.y" />
</template>

<style scoped>
:deep(tbody tr) {
  user-select: none;
  -webkit-touch-callout: none;
}
</style>
