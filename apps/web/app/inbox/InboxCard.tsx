"use client";

import { useState, useTransition } from "react";
import { confirmItem, editItem, rejectItem, type EditItemPatch } from "./actions";
import type { InboxItem } from "./types";
import { Badge } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

const VALID_ITEM_TYPES = [
  "task",
  "finance",
  "calendar",
  "food",
  "exercise",
  "habit",
  "goal",
  "investment",
  "note",
  "journal",
  "unknown",
];

const inputClass =
  "w-full rounded-lg border border-border bg-bg px-2.5 py-1.5 text-sm text-fg outline-none focus-visible:ring-2 focus-visible:ring-accent";

interface EditFormState {
  item_type: string;
  title: string;
  body: string;
  structured_json: string;
}

function toEditForm(item: InboxItem): EditFormState {
  return {
    item_type: item.item_type,
    title: item.title ?? "",
    body: item.body ?? "",
    structured_json: JSON.stringify(item.structured_json, null, 2),
  };
}

export function InboxCard({ item }: { item: InboxItem }) {
  const [isPending, startTransition] = useTransition();
  const [actionError, setActionError] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState<EditFormState>(() => toEditForm(item));
  const [editError, setEditError] = useState<string | null>(null);

  const needsManual = item.review_status === "needs_manual_classification";
  const isPending_ = item.review_status === "pending";
  const canConfirm = isPending_ && item.item_type !== "unknown";
  const canReject = isPending_ || needsManual;

  const displayText =
    item.body || item.capture?.transcript || item.capture?.raw_text || "(no text)";
  const hasStructuredData = Object.keys(item.structured_json).length > 0;

  const sj = item.structured_json as Record<string, unknown>;
  const calories = typeof sj.calories === "number" ? sj.calories : null;
  const foodNutrition =
    item.item_type === "food" && calories !== null
      ? [
          `${Math.round(calories)} kcal`,
          typeof sj.protein_g === "number" ? `P ${Math.round(sj.protein_g)}` : null,
          typeof sj.carbs_g === "number" ? `C ${Math.round(sj.carbs_g)}` : null,
          typeof sj.fat_g === "number" ? `F ${Math.round(sj.fat_g)}` : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : null;

  const exerciseSummary =
    item.item_type === "exercise"
      ? [
          typeof sj.duration_min === "number" ? `${Math.round(sj.duration_min)} min` : null,
          typeof sj.distance_km === "number" ? `${sj.distance_km} km` : null,
          typeof sj.sets === "number" && typeof sj.reps === "number"
            ? `${sj.sets} × ${sj.reps}`
            : null,
          calories !== null ? `${Math.round(calories)} kcal` : null,
        ]
          .filter(Boolean)
          .join(" · ") || null
      : null;

  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);
  const habitSummary =
    item.item_type === "habit"
      ? [str(sj.cadence), str(sj.target) ? `target ${str(sj.target)}` : null]
          .filter(Boolean)
          .join(" · ") || null
      : null;
  const goalSummary =
    item.item_type === "goal"
      ? [str(sj.target), str(sj.target_date) ? `by ${str(sj.target_date)}` : null]
          .filter(Boolean)
          .join(" · ") || null
      : null;

  function handleConfirm() {
    setActionError(null);
    startTransition(async () => {
      const result = await confirmItem(item.id);
      if (!result.ok) {
        setActionError(
          typeof result.data?.detail === "string"
            ? result.data.detail
            : `Confirm failed (${result.status})`
        );
      }
    });
  }

  function handleReject() {
    setActionError(null);
    startTransition(async () => {
      const result = await rejectItem(item.id);
      if (!result.ok) {
        setActionError(
          typeof result.data?.detail === "string"
            ? result.data.detail
            : `Reject failed (${result.status})`
        );
      }
    });
  }

  function handleEditOpen() {
    setEditForm(toEditForm(item));
    setEditError(null);
    setIsEditing(true);
  }

  function handleEditCancel() {
    setIsEditing(false);
    setEditError(null);
  }

  function handleEditSave() {
    setEditError(null);

    let parsedJson: Record<string, unknown>;
    try {
      parsedJson = JSON.parse(editForm.structured_json);
    } catch {
      setEditError("structured_json must be valid JSON");
      return;
    }

    const patch: EditItemPatch = {};
    if (editForm.item_type !== item.item_type) patch.item_type = editForm.item_type;
    if (editForm.title !== (item.title ?? "")) patch.title = editForm.title;
    if (editForm.body !== (item.body ?? "")) patch.body = editForm.body;
    if (JSON.stringify(parsedJson) !== JSON.stringify(item.structured_json)) {
      patch.structured_json = parsedJson;
    }

    if (Object.keys(patch).length === 0) {
      setIsEditing(false);
      return;
    }

    startTransition(async () => {
      const result = await editItem(item.id, patch);
      if (result.ok) {
        setIsEditing(false);
      } else {
        setEditError(
          typeof result.data?.detail === "string"
            ? result.data.detail
            : `Edit failed (${result.status})`
        );
      }
    });
  }

  return (
    <div className="space-y-3 rounded-xl border border-border bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium leading-snug text-fg">
          {item.title ?? displayText.slice(0, 80)}
        </p>
        <div className="flex shrink-0 gap-1.5">
          <Badge tone="neutral" dot={false}>
            {item.item_type}
          </Badge>
          <Badge tone={needsManual ? "warning" : "info"}>{item.review_status}</Badge>
        </div>
      </div>

      {item.image_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={item.image_url}
          alt={item.title ?? "Food photo"}
          className="max-h-56 w-full rounded-lg border border-border object-cover"
        />
      ) : null}

      {foodNutrition ? <p className="numeric text-sm text-muted">{foodNutrition}</p> : null}

      {exerciseSummary ? (
        <p className="numeric text-sm text-muted">{exerciseSummary}</p>
      ) : null}

      {habitSummary ? <p className="text-sm text-muted">{habitSummary}</p> : null}
      {goalSummary ? <p className="text-sm text-muted">{goalSummary}</p> : null}

      {needsManual ? (
        <p className="rounded-lg border border-border bg-surface-raised px-3 py-2 text-xs text-warning">
          Classification failed — edit the item below to correct the type and data.
        </p>
      ) : null}

      {item.body && item.title && item.body !== item.title ? (
        <p className="text-sm leading-relaxed text-muted">{item.body}</p>
      ) : null}

      {hasStructuredData && !isEditing ? (
        <pre className="numeric overflow-x-auto rounded-lg border border-border bg-bg p-3 text-xs leading-relaxed text-muted">
          {JSON.stringify(item.structured_json, null, 2)}
        </pre>
      ) : null}

      {isEditing ? (
        <div className="space-y-3 rounded-lg border border-border bg-surface-raised p-4">
          <div className="space-y-1">
            <label className="block text-xs font-medium text-muted">Type</label>
            <select
              className={inputClass}
              value={editForm.item_type}
              onChange={(e) => setEditForm((f) => ({ ...f, item_type: e.target.value }))}
            >
              {VALID_ITEM_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-muted">Title</label>
            <input
              type="text"
              className={inputClass}
              value={editForm.title}
              onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))}
            />
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-muted">Body</label>
            <textarea
              rows={2}
              className={inputClass}
              value={editForm.body}
              onChange={(e) => setEditForm((f) => ({ ...f, body: e.target.value }))}
            />
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-muted">Structured JSON</label>
            <textarea
              rows={6}
              className={`${inputClass} numeric`}
              value={editForm.structured_json}
              onChange={(e) =>
                setEditForm((f) => ({ ...f, structured_json: e.target.value }))
              }
            />
          </div>

          {editError ? (
            <p className="rounded-lg border border-border bg-bg px-3 py-2 text-xs text-negative">
              {editError}
            </p>
          ) : null}

          <div className="flex gap-2">
            <button
              onClick={handleEditSave}
              disabled={isPending}
              className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg transition-colors hover:bg-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            >
              {isPending ? "Saving…" : "Save"}
            </button>
            <button
              onClick={handleEditCancel}
              disabled={isPending}
              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:bg-surface hover:text-fg disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {actionError ? (
        <p className="rounded-lg border border-border bg-surface-raised px-3 py-2 text-xs text-negative">
          {actionError}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-3">
        <div className="flex flex-1 flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
          {item.capture?.source ? <span>source: {item.capture.source}</span> : null}
          {item.confidence != null ? (
            <span>confidence: {Math.round(item.confidence * 100)}%</span>
          ) : null}
          <span>{fmtDateTime(item.created_at)}</span>
        </div>

        <div className="flex shrink-0 gap-2">
          <button
            onClick={handleEditOpen}
            disabled={isPending || isEditing}
            className="rounded-lg border border-border px-3 py-1 text-xs font-medium text-muted transition-colors hover:bg-surface-raised hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
          >
            Edit
          </button>
          {canReject ? (
            <button
              onClick={handleReject}
              disabled={isPending}
              className="rounded-lg border border-border px-3 py-1 text-xs font-medium text-negative transition-colors hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            >
              {isPending ? "…" : "Reject"}
            </button>
          ) : null}
          {canConfirm ? (
            <button
              onClick={handleConfirm}
              disabled={isPending}
              className="rounded-lg bg-positive px-3 py-1 text-xs font-medium text-white transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            >
              {isPending ? "…" : "Confirm"}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
