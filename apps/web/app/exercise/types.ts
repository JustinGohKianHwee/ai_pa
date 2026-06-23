export interface ExerciseLog {
  id: string;
  inbox_item_id: string;
  activity: string;
  duration_min: number | null;
  distance_km: number | null;
  sets: number | null;
  reps: number | null;
  intensity: string | null;
  calories: number | null;
  logged_at: string | null;
  notes: string | null;
  created_at: string;
}

export interface ExerciseTotals {
  duration_min: number;
  distance_km: number;
  calories: number;
}

export interface ExerciseLogsResponse {
  items: ExerciseLog[];
  total: number;
  totals: ExerciseTotals;
}
