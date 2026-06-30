export type GoalStatus = "active" | "achieved" | "abandoned";

export interface Goal {
  id: string;
  inbox_item_id: string;
  title: string;
  description: string | null;
  target: string | null;
  target_date: string | null;
  status: GoalStatus;
  target_value: number | null;
  target_currency: string | null;
  target_metric: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoalsResponse {
  items: Goal[];
  total: number;
}

export type GoalLinkSource =
  | "tasks"
  | "money_events"
  | "food_logs"
  | "calendar_intents"
  | "exercise_logs"
  | "habits"
  | "decisions"
  | "notes"
  | "journal_entries"
  | "lifestyle_checkins"
  | "manual_financial_snapshots";

export interface GoalLink {
  id: string;
  goal_id: string;
  source_table: GoalLinkSource;
  source_id: string;
  note: string | null;
  created_at: string;
  label: string;
  title: string | null;
}

export interface GoalLinksResponse {
  items: GoalLink[];
  total: number;
}
