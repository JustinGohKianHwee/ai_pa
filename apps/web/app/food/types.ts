export interface FoodLog {
  id: string;
  inbox_item_id: string;
  description: string;
  meal_type: string | null;
  logged_at: string | null;
  created_at: string;
}

export interface FoodLogsResponse {
  items: FoodLog[];
  total: number;
}
