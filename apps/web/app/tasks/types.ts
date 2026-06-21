export interface Task {
  id: string;
  inbox_item_id: string;
  title: string;
  urgency: string | null;
  due_date: string | null;
  notes: string | null;
  status: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TasksResponse {
  items: Task[];
  total: number;
}
