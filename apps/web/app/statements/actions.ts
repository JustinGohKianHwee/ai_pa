"use server";

import { revalidatePath } from "next/cache";
import { authedFetch } from "@/lib/api";
import type { StatementImportResult } from "./types";

export interface UploadResult {
  ok: boolean;
  status: number;
  data: (StatementImportResult & { detail?: string }) | { detail?: string };
}

export async function uploadStatement(formData: FormData): Promise<UploadResult> {
  const file = formData.get("file");
  const defaultCurrency = ((formData.get("default_currency") as string) || "SGD").trim();
  if (!(file instanceof File) || file.size === 0) {
    return { ok: false, status: 400, data: { detail: "Choose a CSV file to upload." } };
  }

  const out = new FormData();
  out.append("file", file, file.name);
  out.append("default_currency", defaultCurrency);

  const res = await authedFetch("/statements/import", { method: "POST", body: out });
  const data = await res.json().catch(() => ({}));
  if (res.ok) revalidatePath("/statements");
  return { ok: res.ok, status: res.status, data };
}
