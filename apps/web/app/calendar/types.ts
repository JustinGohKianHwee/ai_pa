export interface CalendarIntent {
  id: string;
  inbox_item_id: string;
  title: string;
  proposed_datetime: string | null;
  location: string | null;
  notes: string | null;
  created_at: string;
}

export interface CalendarIntentsResponse {
  items: CalendarIntent[];
  total: number;
}
