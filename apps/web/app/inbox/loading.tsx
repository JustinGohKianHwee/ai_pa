import { PageContainer } from "@/components/ui";

export default function InboxLoading() {
  return (
    <PageContainer>
      <div className="mb-6">
        <div className="h-8 w-24 animate-pulse rounded bg-surface-raised" />
        <div className="mt-2 h-4 w-40 animate-pulse rounded bg-surface-raised" />
      </div>
      <div className="space-y-3">
        {[1, 2, 3].map((n) => (
          <div key={n} className="space-y-3 rounded-xl border border-border bg-surface p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="h-5 w-2/3 animate-pulse rounded bg-surface-raised" />
              <div className="flex gap-1.5">
                <div className="h-5 w-16 animate-pulse rounded bg-surface-raised" />
                <div className="h-5 w-16 animate-pulse rounded bg-surface-raised" />
              </div>
            </div>
            <div className="h-4 w-full animate-pulse rounded bg-surface-raised" />
            <div className="h-4 w-3/4 animate-pulse rounded bg-surface-raised" />
          </div>
        ))}
      </div>
    </PageContainer>
  );
}
