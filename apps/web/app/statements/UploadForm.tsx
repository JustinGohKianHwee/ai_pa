"use client";

import { useRef, useState, useTransition } from "react";
import Link from "next/link";
import { uploadStatement } from "./actions";

export function UploadForm() {
  const [isPending, startTransition] = useTransition();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setMsg(null);
    const fd = new FormData(e.currentTarget);
    startTransition(async () => {
      const res = await uploadStatement(fd);
      if (res.ok && "row_count" in res.data) {
        const d = res.data;
        setMsg({
          ok: true,
          text: `Imported ${d.row_count} rows — ${d.matched_count} matched existing expenses, ${d.imported_count} added to your inbox for review.`,
        });
        formRef.current?.reset();
      } else {
        setMsg({
          ok: false,
          text: typeof res.data?.detail === "string" ? res.data.detail : `Upload failed (${res.status})`,
        });
      }
    });
  }

  return (
    <form ref={formRef} onSubmit={onSubmit} className="rounded-xl border border-border bg-surface p-5">
      <p className="text-sm font-medium text-fg">Import a statement (CSV)</p>
      <p className="mt-1 text-xs text-muted">
        Columns: <span className="numeric">date, description, amount</span> (and optional{" "}
        <span className="numeric">currency</span>). Rows matching an existing expense are marked
        verified; the rest become pending items in your inbox to review &amp; confirm.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <input
          type="file"
          name="file"
          accept=".csv,text/csv"
          required
          className="text-sm text-muted file:mr-3 file:rounded-lg file:border file:border-border file:bg-surface-raised file:px-3 file:py-1.5 file:text-sm file:text-fg"
        />
        <input
          type="text"
          name="default_currency"
          defaultValue="SGD"
          aria-label="Default currency"
          className="w-24 rounded-lg border border-border bg-bg px-2.5 py-1.5 text-sm text-fg outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
        <button
          type="submit"
          disabled={isPending}
          className="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
        >
          {isPending ? "Importing…" : "Import"}
        </button>
      </div>
      {msg ? (
        <div
          className={`mt-3 rounded-lg border border-border px-3 py-2 text-xs ${
            msg.ok ? "text-positive" : "text-negative"
          }`}
        >
          {msg.text}
          {msg.ok ? (
            <>
              {" "}
              <Link href="/inbox" className="underline hover:text-fg">
                Go to inbox →
              </Link>
            </>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}
