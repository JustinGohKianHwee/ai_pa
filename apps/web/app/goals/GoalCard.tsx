"use client";

import { useState, useTransition } from "react";
import { Badge } from "@/components/ui";
import { fmtDateTime, type Tone } from "@/lib/format";
import { updateGoalStatus } from "./actions";
import type { Goal, GoalStatus } from "./types";

const STATUS_TONE: Record<GoalStatus, Tone> = {
  active: "info",
  achieved: "positive",
  abandoned: "neutral",
};

const btn =
  "rounded-lg border border-border px-3 py-1 text-xs font-medium text-muted transition-colors hover:bg-surface-raised hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50";

export function GoalCard({ goal }: { goal: Goal }) {
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function setStatus(status: GoalStatus) {
    setError(null);
    startTransition(async () => {
      const res = await updateGoalStatus(goal.id, status);
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
        <p className="font-medium leading-snug text-fg">{goal.title}</p>
        <Badge tone={STATUS_TONE[goal.status] ?? "neutral"} dot={false}>
          {goal.status}
        </Badge>
      </div>
      {goal.description ? (
        <p className="mt-1.5 text-sm text-muted">{goal.description}</p>
      ) : null}
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
        {goal.target ? <span>Target: {goal.target}</span> : null}
        {goal.target_date ? <span>by {goal.target_date}</span> : null}
      </div>
      <p className="mt-2 text-xs text-faint">{fmtDateTime(goal.created_at)}</p>

      {error ? (
        <p className="mt-2 rounded-lg border border-border bg-surface-raised px-3 py-2 text-xs text-negative">
          {error}
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
        {goal.status !== "achieved" ? (
          <button className={btn} disabled={isPending} onClick={() => setStatus("achieved")}>
            Mark achieved
          </button>
        ) : null}
        {goal.status !== "abandoned" ? (
          <button className={btn} disabled={isPending} onClick={() => setStatus("abandoned")}>
            Abandon
          </button>
        ) : null}
        {goal.status !== "active" ? (
          <button className={btn} disabled={isPending} onClick={() => setStatus("active")}>
            Reactivate
          </button>
        ) : null}
      </div>
    </div>
  );
}
