"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, useTransition } from "react";
import type { GoalLink, GoalLinkSource } from "../types";
import { addLink, listForType, removeLink, type LinkRecordOption } from "./actions";

const SOURCE_OPTIONS: { value: GoalLinkSource; label: string; href: string }[] = [
  { value: "tasks", label: "Task", href: "/tasks" },
  { value: "money_events", label: "Expense", href: "/finance" },
  { value: "food_logs", label: "Food", href: "/food" },
  { value: "calendar_intents", label: "Calendar", href: "/calendar" },
  { value: "exercise_logs", label: "Exercise", href: "/exercise" },
  { value: "habits", label: "Habit", href: "/habits" },
  { value: "decisions", label: "Decision", href: "/decisions" },
  { value: "notes", label: "Note", href: "/notes" },
  { value: "journal_entries", label: "Journal", href: "/journal" },
  { value: "lifestyle_checkins", label: "Check-in", href: "/checkins" },
  { value: "manual_financial_snapshots", label: "Snapshot", href: "/financial-intelligence" },
];

const selectClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
const inputClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
const buttonClass =
  "rounded-lg border border-border px-3 py-2 text-sm font-medium text-fg transition-colors hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50";

function linkHref(sourceTable: GoalLinkSource) {
  return SOURCE_OPTIONS.find((source) => source.value === sourceTable)?.href ?? "/goals";
}

function displayTitle(link: GoalLink) {
  return link.title ? `${link.label} · ${link.title}` : link.label;
}

export function LinkManager({ goalId, links }: { goalId: string; links: GoalLink[] }) {
  const router = useRouter();
  const [sourceTable, setSourceTable] = useState<GoalLinkSource>("tasks");
  const [records, setRecords] = useState<LinkRecordOption[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const hasRecords = records.length > 0;
  const existingIds = useMemo(
    () => new Set(links.filter((link) => link.source_table === sourceTable).map((link) => link.source_id)),
    [links, sourceTable]
  );

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRecords([]);
    setSourceId("");

    startTransition(async () => {
      const options = await listForType(sourceTable);
      if (cancelled) return;
      setRecords(options);
      setSourceId(options.find((option) => !existingIds.has(option.id))?.id ?? options[0]?.id ?? "");
    });

    return () => {
      cancelled = true;
    };
  }, [existingIds, sourceTable]);

  function submit() {
    if (!sourceId) {
      setError("Choose a record to link.");
      return;
    }
    setError(null);
    startTransition(async () => {
      const res = await addLink(goalId, { source_table: sourceTable, source_id: sourceId, note });
      if (res.ok) {
        setNote("");
        router.refresh();
        return;
      }
      setError(
        typeof res.data?.detail === "string" ? res.data.detail : `Link failed (${res.status})`
      );
    });
  }

  function remove(linkId: string) {
    setError(null);
    startTransition(async () => {
      const res = await removeLink(goalId, linkId);
      if (!res.ok) {
        setError(
          typeof res.data?.detail === "string"
            ? res.data.detail
            : `Remove failed (${res.status})`
        );
      } else {
        router.refresh();
      }
    });
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-medium text-fg">Linked records</h2>
        <p className="mt-1 text-sm text-muted">
          Manual attribution only. Links are reversible metadata and do not create memory events.
        </p>
      </div>

      {links.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-surface-raised p-4 text-sm text-muted">
          No records linked to this goal yet.
        </div>
      ) : (
        <div className="space-y-2">
          {links.map((link) => (
            <div
              key={link.id}
              className="flex items-start justify-between gap-3 rounded-xl border border-border bg-surface-raised p-3"
            >
              <div className="min-w-0">
                <Link
                  href={linkHref(link.source_table)}
                  className="text-sm font-medium text-fg transition-colors hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  {displayTitle(link)}
                </Link>
                {link.note ? <p className="mt-1 text-sm text-muted">{link.note}</p> : null}
              </div>
              <button
                type="button"
                className="rounded-md px-2 py-1 text-sm text-faint transition-colors hover:bg-surface hover:text-negative focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                disabled={isPending}
                onClick={() => remove(link.id)}
                aria-label={`Remove ${displayTitle(link)}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="rounded-xl border border-border bg-surface-raised p-4">
        <h3 className="text-sm font-medium text-fg">Add a link</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-muted">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              Type
            </span>
            <select
              className={selectClass}
              value={sourceTable}
              onChange={(event) => setSourceTable(event.target.value as GoalLinkSource)}
              disabled={isPending}
            >
              {SOURCE_OPTIONS.map((source) => (
                <option key={source.value} value={source.value}>
                  {source.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-muted">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              Record
            </span>
            <select
              className={selectClass}
              value={sourceId}
              onChange={(event) => setSourceId(event.target.value)}
              disabled={isPending || !hasRecords}
            >
              {hasRecords ? (
                records.map((record) => (
                  <option key={record.id} value={record.id}>
                    {record.label}
                  </option>
                ))
              ) : (
                <option value="">No records available</option>
              )}
            </select>
          </label>
        </div>
        <label className="mt-3 block text-sm text-muted">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
            Optional note
          </span>
          <input
            className={inputClass}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why this supports the goal"
            disabled={isPending}
          />
        </label>
        {error ? <p className="mt-3 text-sm text-negative">{error}</p> : null}
        <button
          type="button"
          className={`${buttonClass} mt-3`}
          disabled={isPending || !sourceId}
          onClick={submit}
        >
          Link record
        </button>
      </div>
    </div>
  );
}
