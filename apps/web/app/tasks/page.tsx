import Link from "next/link";
import type { Task, TasksResponse } from "./types";
import { TaskList } from "./TaskList";

// Always render at request time — never pre-render at build; requires live token + data.
export const dynamic = "force-dynamic";

async function getTasks(): Promise<Task[]> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const token = process.env.DEV_ADMIN_TOKEN;

  if (!token) {
    throw new Error(
      "DEV_ADMIN_TOKEN is not configured. Add it to apps/web/.env.local."
    );
  }

  const res = await fetch(`${apiUrl}/tasks`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });

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
    <main className="min-h-screen bg-gray-50 py-10 px-4">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <Link href="/" className="text-sm text-gray-400 hover:text-gray-600">
            ← Home
          </Link>
          <h1 className="text-2xl font-semibold text-gray-900 mt-2">Tasks</h1>
          <p className="mt-1 text-sm text-gray-500">
            {openCount === 0
              ? "No open tasks"
              : `${openCount} open task${openCount !== 1 ? "s" : ""}`}
          </p>
        </div>

        <TaskList tasks={tasks} />
      </div>
    </main>
  );
}
