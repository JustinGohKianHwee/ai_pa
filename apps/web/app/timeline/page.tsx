import { PageContainer, PageHeader } from "@/components/ui";
import { fetchTimeline } from "./actions";
import { TimelineFeed } from "./TimelineFeed";

export const dynamic = "force-dynamic";

export default async function TimelinePage() {
  const initial = await fetchTimeline({});

  return (
    <PageContainer>
      <PageHeader title="Timeline" subtitle="Everything you've confirmed, newest first" />
      <TimelineFeed
        initialItems={initial.data?.items ?? []}
        initialCursor={initial.data?.next_cursor ?? null}
        initialError={!initial.ok}
      />
    </PageContainer>
  );
}
