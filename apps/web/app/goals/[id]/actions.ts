"use server";

import { revalidatePath } from "next/cache";
import { authedFetch } from "@/lib/api";
import type { GoalLinkSource } from "../types";

interface ApiResult {
  ok: boolean;
  status: number;
  data: Record<string, unknown>;
}

export interface LinkRecordOption {
  id: string;
  label: string;
}

const RECORD_SOURCES: Record<
  GoalLinkSource,
  { endpoint: string; labelField: string; fallback: string }
> = {
  tasks: { endpoint: "/tasks", labelField: "title", fallback: "Task" },
  money_events: { endpoint: "/money_events", labelField: "merchant", fallback: "Expense" },
  decisions: { endpoint: "/decisions", labelField: "decision", fallback: "Decision" },
  notes: { endpoint: "/notes", labelField: "content", fallback: "Note" },
  journal_entries: { endpoint: "/journal", labelField: "content", fallback: "Journal" },
  exercise_logs: { endpoint: "/exercise_logs", labelField: "activity", fallback: "Exercise" },
  food_logs: { endpoint: "/food_logs", labelField: "description", fallback: "Food" },
  calendar_intents: { endpoint: "/calendar_intents", labelField: "title", fallback: "Calendar" },
  habits: { endpoint: "/habits", labelField: "name", fallback: "Habit" },
  lifestyle_checkins: { endpoint: "/checkins", labelField: "mood", fallback: "Check-in" },
  manual_financial_snapshots: {
    endpoint: "/financial_snapshots",
    labelField: "as_of",
    fallback: "Snapshot",
  },
};

function labelFromItem(item: Record<string, unknown>, labelField: string, fallback: string) {
  const raw = item[labelField];
  if (raw === null || raw === undefined || raw === "") return fallback;
  const label = String(raw).trim();
  return label ? label.slice(0, 80) : fallback;
}

export async function listForType(sourceTable: GoalLinkSource): Promise<LinkRecordOption[]> {
  const config = RECORD_SOURCES[sourceTable];
  if (!config) return [];

  const res = await authedFetch(config.endpoint, { cache: "no-store" });
  if (!res.ok) return [];

  const data = (await res.json().catch(() => ({}))) as { items?: Record<string, unknown>[] };
  return (data.items ?? [])
    .filter((item) => typeof item.id === "string")
    .map((item) => ({
      id: item.id as string,
      label: labelFromItem(item, config.labelField, config.fallback),
    }));
}

export async function addLink(
  goalId: string,
  payload: { source_table: GoalLinkSource; source_id: string; note?: string }
): Promise<ApiResult> {
  const res = await authedFetch(`/goals/${goalId}/links`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_table: payload.source_table,
      source_id: payload.source_id,
      note: payload.note?.trim() || null,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) revalidatePath(`/goals/${goalId}`);
  return { ok: res.ok, status: res.status, data };
}

export async function removeLink(goalId: string, linkId: string): Promise<ApiResult> {
  const res = await authedFetch(`/goals/${goalId}/links/${linkId}`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (res.ok) revalidatePath(`/goals/${goalId}`);
  return { ok: res.ok, status: res.status, data };
}
