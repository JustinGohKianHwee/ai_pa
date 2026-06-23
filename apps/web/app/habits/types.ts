export interface Habit {
  id: string;
  inbox_item_id: string;
  name: string;
  cadence: string | null;
  target: string | null;
  notes: string | null;
  created_at: string;
}

export interface HabitsResponse {
  items: Habit[];
  total: number;
}
