import type { AppStatus } from "@/api/types";

export const ACTIVE_STATUSES: AppStatus[] = ["saved", "preparing", "applied", "interviewing", "offer"];
export const TERMINAL_STATUSES: AppStatus[] = ["rejected", "withdrawn", "accepted"];

/** Statuses an application may move to from `from` (spec §5; mirrors backend can_transition). */
export function allowedTargets(from: AppStatus): AppStatus[] {
  if (!ACTIVE_STATUSES.includes(from)) return []; // finished states are left only via reopen
  return [...ACTIVE_STATUSES.filter((s) => s !== from), "rejected", "withdrawn", ...(from === "offer" ? (["accepted"] as AppStatus[]) : [])];
}
