import type { Task, TasksResponse } from "./types";
import { TaskList } from "./TaskList";
import { authedFetch } from "@/lib/api";
import { PageContainer, PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

async function getTasks(): Promise<Task[]> {
  const res = await authedFetch("/tasks", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Backend returned ${res.status}: ${res.statusText}`);
  }
  const data: TasksResponse = await res.json();
  return data.items;
}

export default async function TasksPage() {
  const tasks = await getTasks();
  const openCount = tasks.filter((t) => t.status === "open").length;

  return (
    <PageContainer>
      <PageHeader
        title="Tasks"
        subtitle={
          openCount === 0 ? "No open tasks" : `${openCount} open task${openCount !== 1 ? "s" : ""}`
        }
      />
      <TaskList tasks={tasks} />
    </PageContainer>
  );
}
