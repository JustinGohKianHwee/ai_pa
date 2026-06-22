"use client";

import { useState, useTransition } from "react";
import { completeTask } from "./actions";
import type { Task } from "./types";
import { fmtDateTime } from "@/lib/format";
import { EmptyState } from "@/components/ui";

const URGENCY_GROUPS: { key: string | null; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "this_week", label: "This week" },
  { key: "someday", label: "Someday" },
  { key: null, label: "Unscheduled" },
];

function CompleteButton({ id }: { id: string }) {
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function handleComplete() {
    setError(null);
    startTransition(async () => {
      const result = await completeTask(id);
      if (!result.ok) {
        setError(
          typeof result.data?.detail === "string"
            ? result.data.detail
            : `Failed (${result.status})`
        );
      }
    });
  }

  return (
    <div className="flex shrink-0 flex-col items-end gap-1">
      <button
        onClick={handleComplete}
        disabled={isPending}
        className="rounded-lg border border-border px-3 py-1 text-xs font-medium text-positive transition-colors hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
      >
        {isPending ? "…" : "Mark complete"}
      </button>
      {error ? <span className="max-w-[12rem] text-right text-xs text-negative">{error}</span> : null}
    </div>
  );
}

function TaskCard({ task, completed = false }: { task: Task; completed?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-border bg-surface p-4">
      <div className="min-w-0">
        <p className={completed ? "leading-snug text-faint line-through" : "font-medium leading-snug text-fg"}>
          {task.title}
        </p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
          {task.due_date ? <span>due: {task.due_date}</span> : null}
          {task.notes ? <span className="text-muted">{task.notes}</span> : null}
          <span>{fmtDateTime(task.created_at)}</span>
        </div>
      </div>
      {!completed ? <CompleteButton id={task.id} /> : null}
    </div>
  );
}

export function TaskList({ tasks }: { tasks: Task[] }) {
  const open = tasks.filter((t) => t.status === "open");
  const completed = tasks.filter((t) => t.status === "completed");

  if (tasks.length === 0) {
    return <EmptyState>No tasks yet. Confirm a task in the inbox to see it here.</EmptyState>;
  }

  return (
    <div className="space-y-8">
      <div className="space-y-6">
        {open.length === 0 ? <p className="text-sm text-faint">No open tasks.</p> : null}
        {URGENCY_GROUPS.map((group) => {
          const groupTasks = open.filter((t) => (t.urgency ?? null) === group.key);
          if (groupTasks.length === 0) return null;
          return (
            <section key={group.label} className="space-y-2">
              <h2 className="text-xs font-medium uppercase tracking-wider text-faint">
                {group.label}
              </h2>
              {groupTasks.map((t) => (
                <TaskCard key={t.id} task={t} />
              ))}
            </section>
          );
        })}
      </div>

      {completed.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-xs font-medium uppercase tracking-wider text-faint">Completed</h2>
          {completed.map((t) => (
            <TaskCard key={t.id} task={t} completed />
          ))}
        </section>
      ) : null}
    </div>
  );
}
