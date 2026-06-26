export interface Checkin {
  id: string;
  inbox_item_id: string;
  as_of: string | null;
  energy: number | null;
  mood: string | null;
  sleep_hours: number | null;
  stress: number | null;
  activity: string | null;
  notes: string | null;
  created_at: string;
}

export interface CheckinsResponse {
  items: Checkin[];
  total: number;
}
