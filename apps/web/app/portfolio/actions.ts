"use server";

import { revalidatePath } from "next/cache";
import { authedFetch } from "@/lib/api";

export interface SnapshotActionResult {
  ok: boolean;
  status: number;
  detail?: string;
  snapshotDate?: string;
}

export async function snapshotToday(): Promise<SnapshotActionResult> {
  const response = await authedFetch("/portfolio/snapshots", { method: "POST" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      detail: typeof data.detail === "string" ? data.detail : "Snapshot failed",
    };
  }

  revalidatePath("/portfolio");
  revalidatePath("/portfolio/history");
  return {
    ok: true,
    status: response.status,
    snapshotDate:
      typeof data.snapshot_date === "string" ? data.snapshot_date : undefined,
  };
}
