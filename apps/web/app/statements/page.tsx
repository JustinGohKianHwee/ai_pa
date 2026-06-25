import type { StatementImportsResponse } from "./types";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader, EmptyState } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";
import { UploadForm } from "./UploadForm";

export const dynamic = "force-dynamic";

async function getImports(): Promise<StatementImportsResponse | null> {
  try {
    const res = await authedFetch("/statements", { cache: "no-store" });
    return res.ok ? ((await res.json()) as StatementImportsResponse) : null;
  } catch (e) {
    const digest = (e as { digest?: string })?.digest;
    if (typeof digest === "string" && digest.startsWith("NEXT_REDIRECT")) throw e;
    return null;
  }
}

export default async function StatementsPage() {
  const data = await getImports();

  return (
    <PageContainer>
      <PageHeader
        title="Statements"
        subtitle="Import a bank/card statement to reconcile against your logged expenses"
      />

      <UploadForm />

      <div className="mt-6 space-y-2">
        {data === null ? (
          <EmptyState>
            Couldn&apos;t load past imports. If this persists, the database migration (0019) may not
            be applied yet.
          </EmptyState>
        ) : data.items.length === 0 ? (
          <EmptyState>No statements imported yet.</EmptyState>
        ) : (
          data.items.map((imp) => (
            <div key={imp.id} className="rounded-xl border border-border bg-surface p-4">
              <div className="flex items-start justify-between gap-3">
                <p className="font-medium text-fg">{imp.source_label ?? "statement.csv"}</p>
                <span className="text-xs text-faint">{fmtDateTime(imp.created_at)}</span>
              </div>
              <p className="numeric mt-1 text-sm text-muted">
                {imp.row_count} rows · {imp.matched_count} matched · {imp.imported_count} sent to
                inbox
              </p>
            </div>
          ))
        )}
      </div>

      <p className="mt-6 text-xs text-faint">
        Matching is deterministic (currency + amount). Imported rows never become expenses
        automatically — they enter the inbox and follow the normal review → confirm flow.
      </p>
    </PageContainer>
  );
}
