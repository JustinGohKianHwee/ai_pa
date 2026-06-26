export interface Note {
  id: string;
  inbox_item_id: string;
  content: string;
  tags: string[];
  created_at: string;
}

export interface NotesResponse {
  items: Note[];
  total: number;
}
