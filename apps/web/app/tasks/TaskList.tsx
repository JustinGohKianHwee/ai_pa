"use client";

import { useState, useTransition } from "react";
import { completeTask } from "./actions";
import type { Task } from "./types";

const URGENCY_GROUPS: { key: string | null; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "this_week", label: "This week" },
  { key: "someday", label: "Someday" },
  { key: null, label: "Unscheduled" },
];

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function CompleteButton({ id }: { id: string }) {
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function handleComplete() {
    setError(null);
    startTransition(async () => {
      const result = await completeTask(id);
      if (!result.ok) {
        const detail =
          typeof result.data?.detail === "string"
            ? result.data.detail
            : `Failed (${result.status})`;
        setError(detail);
      }
    });
  }

  return (
    <div className="flex flex-col items-end gap-1 shrink-0">
      <button
        onClick={handleComplete}
        disabled={isPending}
        className="px-3 py-1 text-xs font-medium rounded border border-green-300 text-green-700 hover:bg-green-50 disabled:opacity-50"
      >
        {isPending ? "…" : "Mark complete"}
      </button>
      {error && <span className="text-xs text-red-600 max-w-[12rem] text-right">{error}</span>}
    </div>
  );
}

function TaskCard({ task, completed = false }: { task: Task; completed?: boolean }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p
          className={
            completed
              ? "text-gray-400 line-through leading-snug"
              : "font-medium text-gray-900 leading-snug"
          }
        >
          {task.title}
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400 mt-2">
          {task.due_date && <span>due: {task.due_date}</span>}
          {task.notes && <span className="text-gray-500">{task.notes}</span>}
          <span>{formatDate(task.created_at)}</span>
        </div>
      </div>
      {!completed && <CompleteButton id={task.id} />}
    </div>
  );
}

export function TaskList({ tasks }: { tasks: Task[] }) {
  const open = tasks.filter((t) => t.status === "open");
  const completed = tasks.filter((t) => t.status === "completed");

  if (tasks.length === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-12 text-center">
        <p className="text-gray-400 text-sm">No tasks yet.</p>
        <p className="text-gray-400 text-sm mt-1">
          Confirm a task in the inbox to see it here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="space-y-6">
        {open.length === 0 && (
          <p className="text-sm text-gray-400">No open tasks.</p>
        )}
        {URGENCY_GROUPS.map((group) => {
          const groupTasks = open.filter((t) => (t.urgency ?? null) === group.key);
          if (groupTasks.length === 0) return null;
          return (
            <section key={group.label} className="space-y-2">
              <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                {group.label}
              </h2>
              {groupTasks.map((t) => (
                <TaskCard key={t.id} task={t} />
              ))}
            </section>
          );
        })}
      </div>

      {completed.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
            Completed
          </h2>
          {completed.map((t) => (
            <TaskCard key={t.id} task={t} completed />
          ))}
        </section>
      )}
    </div>
  );
}
