"use server";

import { revalidatePath } from "next/cache";
import { authedFetch } from "@/lib/api";
import type { GoalStatus } from "./types";

interface ApiResult {
  ok: boolean;
  status: number;
  data: Record<string, unknown>;
}

export async function updateGoalStatus(
  id: string,
  status: GoalStatus
): Promise<ApiResult> {
  const res = await authedFetch(`/goals/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) revalidatePath("/goals");
  return { ok: res.ok, status: res.status, data };
}
