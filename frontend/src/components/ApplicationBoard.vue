<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { VueDraggable } from "vue-draggable-plus";
import type { AppStatus, ApplicationOut } from "@/api/types";
import ApplicationContextMenu from "@/components/ApplicationContextMenu.vue";
import { useLongPress } from "@/composables/useLongPress";
import { useApplicationsStore } from "@/stores/applications";

const { t } = useI18n();
const router = useRouter();
const store = useApplicationsStore();

const menu = ref({ open: false, x: 0, y: 0, app: null as ApplicationOut | null });

function openMenu(e: MouseEvent, a: ApplicationOut) {
  menu.value = { open: true, x: e.clientX, y: e.clientY, app: a };
}

const longPress = useLongPress((e) => {
  const id = Number((e.target as HTMLElement | null)?.closest<HTMLElement>("[data-id]")?.dataset.id);
  const a = store.items.find((x) => x.id === id);
  if (a) openMenu(e, a);
});

function daysSince(a: ApplicationOut): number {
  const t0 = new Date(a.last_status_change_at ?? a.created_at).getTime();
  return Math.max(0, Math.floor((Date.now() - t0) / 86400_000));
}

function onAdd(status: AppStatus, evt: { item: HTMLElement }) {
  const id = Number(evt.item.dataset.id);
  if (Number.isFinite(id)) void store.move(id, status);
}
</script>

<template>
  <div class="board d-flex ga-3 align-start">
    <div v-for="s in store.visibleStatuses" :key="s" class="column" :data-status="s">
      <div class="text-subtitle-2 mb-2">{{ t(`status.${s}`) }} ({{ store.byStatus[s].length }})</div>
      <!-- One-way list: Sortable only reports the drop, the store owns the data (and rolls back on errors). -->
      <VueDraggable
        :model-value="store.byStatus[s]"
        group="applications"
        item-key="id"
        class="drop-zone"
        :delay="700"
        :delay-on-touch-only="true"
        @start="longPress.cancel"
        @add="onAdd(s, $event)"
      >
        <v-card
          v-for="a in store.byStatus[s]"
          :key="a.id"
          :data-id="a.id"
          class="mb-2"
          variant="outlined"
          @click="router.push('/applications/' + a.id)"
          @contextmenu.prevent="openMenu($event, a)"
          @pointerdown="longPress.onPointerdown"
          @pointermove="longPress.onPointermove"
          @pointerup="longPress.onPointerup"
          @pointercancel="longPress.onPointercancel"
          @pointerleave="longPress.onPointerleave"
          @click.capture="longPress.onClickCapture"
        >
          <v-card-text class="py-2">
            <div class="font-weight-medium">{{ a.posting.title || t("applications.untitled") }}</div>
            <div class="text-body-2">{{ a.posting.company || t("applications.noCompany") }}</div>
            <div class="text-caption text-medium-emphasis">{{ t("applications.daysSince", daysSince(a)) }}</div>
          </v-card-text>
        </v-card>
      </VueDraggable>
    </div>
    <ApplicationContextMenu v-model="menu.open" :application="menu.app" :x="menu.x" :y="menu.y" />
  </div>
</template>

<style scoped>
.board {
  overflow-x: auto;
}
.column {
  flex: 0 0 260px;
  min-width: 260px;
}
.drop-zone {
  min-height: 80px;
}
.drop-zone .v-card {
  cursor: grab;
  user-select: none;
  -webkit-touch-callout: none;
}
</style>
