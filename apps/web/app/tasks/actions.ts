"use server";

import { revalidatePath } from "next/cache";
import { authedFetch } from "@/lib/api";

interface ApiResult {
  ok: boolean;
  status: number;
  data: Record<string, unknown>;
}

async function callApi(
  path: string,
  method: string,
  body?: unknown
): Promise<ApiResult> {
  const res = await authedFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

export async function completeTask(id: string): Promise<ApiResult> {
  const result = await callApi(`/tasks/${id}/complete`, "PATCH");
  if (result.ok) revalidatePath("/tasks");
  return result;
}
