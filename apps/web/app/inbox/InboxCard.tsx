"use client";

import { useState, useTransition } from "react";
import { confirmItem, editItem, rejectItem, type EditItemPatch } from "./actions";
import type { InboxItem } from "./types";

const VALID_ITEM_TYPES = [
  "task",
  "finance",
  "calendar",
  "food",
  "investment",
  "note",
  "journal",
  "unknown",
];

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function ItemTypeBadge({ type }: { type: string }) {
  return (
    <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">
      {type}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles =
    status === "needs_manual_classification"
      ? "bg-amber-100 text-amber-700"
      : "bg-blue-50 text-blue-600";
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${styles}`}
    >
      {status}
    </span>
  );
}

interface EditFormState {
  item_type: string;
  title: string;
  body: string;
  structured_json: string; // raw JSON string for the textarea
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
    item.body ||
    item.capture?.transcript ||
    item.capture?.raw_text ||
    "(no text)";
  const hasStructuredData = Object.keys(item.structured_json).length > 0;

  function handleConfirm() {
    setActionError(null);
    startTransition(async () => {
      const result = await confirmItem(item.id);
      if (!result.ok) {
        const detail =
          typeof result.data?.detail === "string"
            ? result.data.detail
            : `Confirm failed (${result.status})`;
        setActionError(detail);
      }
    });
  }

  function handleReject() {
    setActionError(null);
    startTransition(async () => {
      const result = await rejectItem(item.id);
      if (!result.ok) {
        const detail =
          typeof result.data?.detail === "string"
            ? result.data.detail
            : `Reject failed (${result.status})`;
        setActionError(detail);
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
    // Compare normalized JSON, not the raw textarea string — otherwise pretty-print
    // whitespace makes an unchanged object look edited and re-sends it every time.
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
        const detail =
          typeof result.data?.detail === "string"
            ? result.data.detail
            : `Edit failed (${result.status})`;
        setEditError(detail);
      }
    });
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium text-gray-900 leading-snug">
          {item.title ?? displayText.slice(0, 80)}
        </p>
        <div className="flex gap-1.5 shrink-0">
          <ItemTypeBadge type={item.item_type} />
          <StatusBadge status={item.review_status} />
        </div>
      </div>

      {/* Manual classification warning */}
      {needsManual && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
          Classification failed — edit the item below to correct the type and data.
        </p>
      )}

      {/* Body text */}
      {item.body && item.title && item.body !== item.title && (
        <p className="text-sm text-gray-500 leading-relaxed">{item.body}</p>
      )}

      {/* Structured JSON (read mode) */}
      {hasStructuredData && !isEditing && (
        <pre className="text-xs bg-gray-50 border border-gray-100 rounded p-3 overflow-x-auto text-gray-600 leading-relaxed">
          {JSON.stringify(item.structured_json, null, 2)}
        </pre>
      )}

      {/* Edit form */}
      {isEditing && (
        <div className="space-y-3 border border-gray-200 rounded-lg p-4 bg-gray-50">
          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-600">
              Type
            </label>
            <select
              className="w-full text-sm border border-gray-300 rounded px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={editForm.item_type}
              onChange={(e) =>
                setEditForm((f) => ({ ...f, item_type: e.target.value }))
              }
            >
              {VALID_ITEM_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-600">
              Title
            </label>
            <input
              type="text"
              className="w-full text-sm border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={editForm.title}
              onChange={(e) =>
                setEditForm((f) => ({ ...f, title: e.target.value }))
              }
            />
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-600">
              Body
            </label>
            <textarea
              rows={2}
              className="w-full text-sm border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={editForm.body}
              onChange={(e) =>
                setEditForm((f) => ({ ...f, body: e.target.value }))
              }
            />
          </div>

          <div className="space-y-1">
            <label className="block text-xs font-medium text-gray-600">
              Structured JSON
            </label>
            <textarea
              rows={6}
              className="w-full font-mono text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
              value={editForm.structured_json}
              onChange={(e) =>
                setEditForm((f) => ({ ...f, structured_json: e.target.value }))
              }
            />
          </div>

          {editError && (
            <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
              {editError}
            </p>
          )}

          <div className="flex gap-2">
            <button
              onClick={handleEditSave}
              disabled={isPending}
              className="px-3 py-1.5 text-xs font-medium rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {isPending ? "Saving…" : "Save"}
            </button>
            <button
              onClick={handleEditCancel}
              disabled={isPending}
              className="px-3 py-1.5 text-xs font-medium rounded border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Action error */}
      {actionError && (
        <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          {actionError}
        </p>
      )}

      {/* Metadata + action buttons */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-gray-100 pt-3">
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400 flex-1">
          {item.capture?.source && <span>source: {item.capture.source}</span>}
          {item.confidence != null && (
            <span>confidence: {Math.round(item.confidence * 100)}%</span>
          )}
          <span>{formatDate(item.created_at)}</span>
        </div>

        <div className="flex gap-2 shrink-0">
          <button
            onClick={handleEditOpen}
            disabled={isPending || isEditing}
            className="px-3 py-1 text-xs font-medium rounded border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            Edit
          </button>
          {canReject && (
            <button
              onClick={handleReject}
              disabled={isPending}
              className="px-3 py-1 text-xs font-medium rounded border border-red-300 text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              {isPending ? "…" : "Reject"}
            </button>
          )}
          {canConfirm && (
            <button
              onClick={handleConfirm}
              disabled={isPending}
              className="px-3 py-1 text-xs font-medium rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
            >
              {isPending ? "…" : "Confirm"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
