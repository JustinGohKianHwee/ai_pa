"use server";

import { authedFetch } from "@/lib/api";
import type { TimelineResponse } from "./types";

export interface FetchTimelineParams {
  domains?: string[];
  from?: string;
  to?: string;
  cursor?: string;
}

export interface FetchTimelineResult {
  ok: boolean;
  status: number;
  data: TimelineResponse | null;
}

export async function fetchTimeline(
  params: FetchTimelineParams = {}
): Promise<FetchTimelineResult> {
  const qs = new URLSearchParams();
  if (params.domains && params.domains.length > 0) {
    qs.set("domains", params.domains.join(","));
  }
  if (params.from) qs.set("from", params.from);
  if (params.to) qs.set("to", params.to);
  if (params.cursor) qs.set("cursor", params.cursor);

  const suffix = qs.toString();
  const res = await authedFetch(`/timeline${suffix ? `?${suffix}` : ""}`, {
    cache: "no-store",
  });
  const data = res.ok ? ((await res.json()) as TimelineResponse) : null;
  return { ok: res.ok, status: res.status, data };
}
