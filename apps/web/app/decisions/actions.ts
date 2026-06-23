"use server";

import { revalidatePath } from "next/cache";
import { authedFetch } from "@/lib/api";
import type { DecisionStatus } from "./types";

interface ApiResult {
  ok: boolean;
  status: number;
  data: Record<string, unknown>;
}

export async function updateDecisionStatus(
  id: string,
  status: DecisionStatus
): Promise<ApiResult> {
  const res = await authedFetch(`/decisions/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) revalidatePath("/decisions");
  return { ok: res.ok, status: res.status, data };
}
