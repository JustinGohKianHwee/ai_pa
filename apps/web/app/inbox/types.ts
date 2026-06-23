export interface CaptureContext {
  source: string;
  raw_text: string | null;
  transcript: string | null;
  processing_status: string;
}

export interface InboxItem {
  id: string;
  capture_event_id: string | null;
  item_type: string;
  review_status: string;
  title: string | null;
  body: string | null;
  structured_json: Record<string, unknown>;
  confidence: number | null;
  created_at: string;
  updated_at: string;
  reviewed_at: string | null;
  capture: CaptureContext | null;
  image_url: string | null;
}

export interface InboxResponse {
  items: InboxItem[];
  total: number;
}
