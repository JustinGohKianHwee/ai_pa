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

export async function confirmItem(id: string): Promise<ApiResult> {
  const result = await callApi(`/inbox/${id}/confirm`, "PATCH");
  if (result.ok) revalidatePath("/inbox");
  return result;
}

export async function rejectItem(id: string): Promise<ApiResult> {
  const result = await callApi(`/inbox/${id}/reject`, "PATCH");
  if (result.ok) revalidatePath("/inbox");
  return result;
}

export interface EditItemPatch {
  item_type?: string;
  title?: string;
  body?: string;
  structured_json?: Record<string, unknown>;
}

export async function editItem(
  id: string,
  patch: EditItemPatch
): Promise<ApiResult> {
  const result = await callApi(`/inbox/${id}`, "PATCH", patch);
  if (result.ok) revalidatePath("/inbox");
  return result;
}
