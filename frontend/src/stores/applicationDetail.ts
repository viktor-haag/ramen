import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "@/api/client";
import type {
  AppStatus,
  ApplicationDetailOut,
  ApplicationPatch,
  AppointmentIn,
  AppointmentOut,
  AppointmentPatch,
  AttachmentKind,
  AttachmentOut,
  ContactIn,
  ContactOut,
  ContactPatch,
} from "@/api/types";
import { i18n } from "@/i18n";
import { useNotifyStore } from "@/stores/notify";

export const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;

const byStart = (a: AppointmentOut, b: AppointmentOut) => a.starts_at.localeCompare(b.starts_at);

/** State of the application detail page. Mutations report errors via notify and return success. */
export const useApplicationDetailStore = defineStore("applicationDetail", () => {
  const app = ref<ApplicationDetailOut | null>(null);
  const loading = ref(false);
  let generation = 0;

  /** Drop the loaded application (data was wiped on the server). */
  function clear() {
    generation++;
    app.value = null;
    loading.value = false;
  }

  async function load(id: number) {
    const mine = ++generation;
    if (app.value?.id !== id) app.value = null;
    loading.value = true;
    try {
      const d = await api.get<ApplicationDetailOut>(`/applications/${id}`);
      if (mine === generation) app.value = d;
    } catch (e) {
      if (mine === generation) useNotifyStore().error(e);
    } finally {
      if (mine === generation) loading.value = false;
    }
  }

  async function guarded<T>(fn: (a: ApplicationDetailOut) => Promise<T>): Promise<T | undefined> {
    const a = app.value;
    if (!a) return undefined;
    try {
      const res = await fn(a);
      return res;
    } catch (e) {
      useNotifyStore().error(e);
      return undefined;
    }
  }

  /** The loaded application if it is still the one with this id (it may have been replaced by adopt()). */
  function current(id: number): ApplicationDetailOut | null {
    return app.value?.id === id ? app.value : null;
  }

  /** Replace local state with the server's answer, unless another application was loaded meanwhile. */
  function adopt(id: number, d: ApplicationDetailOut) {
    if (app.value?.id === id) app.value = d;
  }

  async function changeStatus(to: AppStatus, comment?: string | null): Promise<boolean> {
    const r = await guarded(async (a) => {
      const d = await api.post<ApplicationDetailOut>(`/applications/${a.id}/status`, { to, comment: comment || null });
      adopt(a.id, d);
      return true;
    });
    return r === true;
  }

  async function reopen(to: AppStatus, comment?: string | null): Promise<boolean> {
    const r = await guarded(async (a) => {
      const d = await api.post<ApplicationDetailOut>(`/applications/${a.id}/reopen`, { to, comment: comment || null });
      adopt(a.id, d);
      return true;
    });
    return r === true;
  }

  async function patch(body: ApplicationPatch): Promise<boolean> {
    const r = await guarded(async (a) => {
      const d = await api.patch<ApplicationDetailOut>(`/applications/${a.id}`, body);
      adopt(a.id, d);
      return true;
    });
    return r === true;
  }

  // --- appointments ---
  async function addAppointment(body: AppointmentIn): Promise<boolean> {
    const r = await guarded(async (a) => {
      const o = await api.post<AppointmentOut>(`/applications/${a.id}/appointments`, body);
      const c = current(a.id);
      if (c) c.appointments = [...c.appointments, o].sort(byStart);
      return true;
    });
    return r === true;
  }
  async function updateAppointment(id: number, body: AppointmentPatch): Promise<boolean> {
    const r = await guarded(async (a) => {
      const o = await api.patch<AppointmentOut>(`/appointments/${id}`, body);
      const c = current(a.id);
      if (c) c.appointments = c.appointments.map((x) => (x.id === id ? o : x)).sort(byStart);
      return true;
    });
    return r === true;
  }
  async function removeAppointment(id: number): Promise<boolean> {
    const r = await guarded(async (a) => {
      await api.del(`/appointments/${id}`);
      const c = current(a.id);
      if (c) c.appointments = c.appointments.filter((x) => x.id !== id);
      return true;
    });
    return r === true;
  }

  // --- contacts ---
  async function addContact(body: ContactIn): Promise<boolean> {
    const r = await guarded(async (a) => {
      const o = await api.post<ContactOut>(`/applications/${a.id}/contacts`, body);
      const c = current(a.id);
      if (c) c.contacts = [...c.contacts, o];
      return true;
    });
    return r === true;
  }
  async function updateContact(id: number, body: ContactPatch): Promise<boolean> {
    const r = await guarded(async (a) => {
      const o = await api.patch<ContactOut>(`/contacts/${id}`, body);
      const c = current(a.id);
      if (c) c.contacts = c.contacts.map((x) => (x.id === id ? o : x));
      return true;
    });
    return r === true;
  }
  async function removeContact(id: number): Promise<boolean> {
    const r = await guarded(async (a) => {
      await api.del(`/contacts/${id}`);
      const c = current(a.id);
      if (c) c.contacts = c.contacts.filter((x) => x.id !== id);
      return true;
    });
    return r === true;
  }

  // --- attachments ---
  async function uploadAttachment(file: File, kind: AttachmentKind): Promise<boolean> {
    if (file.size > MAX_ATTACHMENT_BYTES) {
      useNotifyStore().show(i18n.global.t("errors.attachment_too_large", { max_mb: MAX_ATTACHMENT_BYTES / (1024 * 1024) }));
      return false;
    }
    const r = await guarded(async (a) => {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      const o = await api.upload<AttachmentOut>(`/applications/${a.id}/attachments`, form);
      const c = current(a.id);
      if (c) c.attachments = [...c.attachments, o];
      return true;
    });
    return r === true;
  }
  async function removeAttachment(id: number): Promise<boolean> {
    const r = await guarded(async (a) => {
      await api.del(`/attachments/${id}`);
      const c = current(a.id);
      if (c) c.attachments = c.attachments.filter((x) => x.id !== id);
      return true;
    });
    return r === true;
  }

  return {
    app, loading, load, clear, changeStatus, reopen, patch,
    addAppointment, updateAppointment, removeAppointment,
    addContact, updateContact, removeContact,
    uploadAttachment, removeAttachment,
  };
});
