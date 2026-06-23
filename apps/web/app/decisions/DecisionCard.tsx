"use client";

import { useState, useTransition } from "react";
import { Badge } from "@/components/ui";
import { fmtDateTime, type Tone } from "@/lib/format";
import { updateDecisionStatus } from "./actions";
import type { Decision, DecisionStatus } from "./types";

const STATUS_TONE: Record<DecisionStatus, Tone> = {
  active: "info",
  reversed: "warning",
  archived: "neutral",
};

const btn =
  "rounded-lg border border-border px-3 py-1 text-xs font-medium text-muted transition-colors hover:bg-surface-raised hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50";

export function DecisionCard({ decision }: { decision: Decision }) {
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function setStatus(status: DecisionStatus) {
    setError(null);
    startTransition(async () => {
      const res = await updateDecisionStatus(decision.id, status);
      if (!res.ok) {
        setError(
          typeof res.data?.detail === "string"
            ? res.data.detail
            : `Update failed (${res.status})`
        );
      }
    });
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium leading-snug text-fg">{decision.decision}</p>
        <div className="flex shrink-0 items-center gap-1.5">
          {decision.category ? (
            <Badge tone="neutral" dot={false}>
              {decision.category}
            </Badge>
          ) : null}
          <Badge tone={STATUS_TONE[decision.status] ?? "neutral"} dot={false}>
            {decision.status}
          </Badge>
        </div>
      </div>

      {decision.reason ? (
        <p className="mt-1.5 text-sm text-muted">
          <span className="text-faint">Why:</span> {decision.reason}
        </p>
      ) : null}
      {decision.options_considered ? (
        <p className="mt-1 text-sm text-muted">
          <span className="text-faint">Options:</span> {decision.options_considered}
        </p>
      ) : null}
      {decision.expected_outcome ? (
        <p className="mt-1 text-sm text-muted">
          <span className="text-faint">Expected:</span> {decision.expected_outcome}
        </p>
      ) : null}

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
        {decision.confidence != null ? (
          <span className="numeric">confidence: {Math.round(decision.confidence * 100)}%</span>
        ) : null}
        {decision.decided_at ? <span>decided: {decision.decided_at}</span> : null}
        <span>{fmtDateTime(decision.created_at)}</span>
      </div>

      {error ? (
        <p className="mt-2 rounded-lg border border-border bg-surface-raised px-3 py-2 text-xs text-negative">
          {error}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
        {decision.status !== "reversed" ? (
          <button className={btn} disabled={isPending} onClick={() => setStatus("reversed")}>
            Reverse
          </button>
        ) : null}
        {decision.status !== "archived" ? (
          <button className={btn} disabled={isPending} onClick={() => setStatus("archived")}>
            Archive
          </button>
        ) : null}
        {decision.status !== "active" ? (
          <button className={btn} disabled={isPending} onClick={() => setStatus("active")}>
            Reactivate
          </button>
        ) : null}
      </div>
    </div>
  );
}
