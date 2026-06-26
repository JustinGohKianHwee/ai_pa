export interface JournalEntry {
  id: string;
  inbox_item_id: string;
  content: string;
  mood: string | null;
  created_at: string;
}

export interface JournalResponse {
  items: JournalEntry[];
  total: number;
}
