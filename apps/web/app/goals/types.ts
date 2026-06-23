export type GoalStatus = "active" | "achieved" | "abandoned";

export interface Goal {
  id: string;
  inbox_item_id: string;
  title: string;
  description: string | null;
  target: string | null;
  target_date: string | null;
  status: GoalStatus;
  created_at: string;
  updated_at: string;
}

export interface GoalsResponse {
  items: Goal[];
  total: number;
}
