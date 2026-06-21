"use server";

import { revalidatePath } from "next/cache";

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// DEV_ADMIN_TOKEN has no NEXT_PUBLIC_ prefix — server-side only, never in the browser.
const token = () => process.env.DEV_ADMIN_TOKEN;

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
  const t = token();
  if (!t) {
    return { ok: false, status: 0, data: { detail: "DEV_ADMIN_TOKEN is not configured" } };
  }

  try {
    const res = await fetch(`${apiUrl()}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${t}`,
        "Content-Type": "application/json",
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0, data: { detail: "Could not reach the backend" } };
  }
}

export async function completeTask(id: string): Promise<ApiResult> {
  const result = await callApi(`/tasks/${id}/complete`, "PATCH");
  if (result.ok) revalidatePath("/tasks");
  return result;
}
