export interface FoodLog {
  id: string;
  inbox_item_id: string;
  description: string;
  meal_type: string | null;
  logged_at: string | null;
  calories: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  image_url: string | null;
  created_at: string;
}

export interface FoodTotals {
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

export interface FoodLogsResponse {
  items: FoodLog[];
  total: number;
  totals: FoodTotals;
}
