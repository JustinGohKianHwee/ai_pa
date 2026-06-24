export interface TimelineEntry {
  id: string;
  occurred_at: string;
  domain: string;
  event_type: string;
  source_table: string | null;
  source_id: string | null;
  payload: Record<string, unknown>;
}

export interface TimelineResponse {
  items: TimelineEntry[];
  next_cursor: string | null;
}

// Filter chips, in display order. Values match memory_events.domain.
export const TIMELINE_DOMAINS: { value: string; label: string }[] = [
  { value: "task", label: "Tasks" },
  { value: "money", label: "Money" },
  { value: "food", label: "Food" },
  { value: "exercise", label: "Exercise" },
  { value: "habit", label: "Habits" },
  { value: "goal", label: "Goals" },
  { value: "decision", label: "Decisions" },
  { value: "financial_snapshot", label: "Finances" },
  { value: "calendar", label: "Calendar" },
  { value: "portfolio_snapshot", label: "Portfolio" },
];
