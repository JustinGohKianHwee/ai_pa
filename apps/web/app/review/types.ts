export interface InboxItemSummary {
  id: string;
  item_type: string;
  review_status: string;
  title: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface CaptureSummary {
  capture_id: string;
  source: string;
  captured_at: string;
  inbox_item_id: string | null;
  item_type: string | null;
  review_status: string | null;
  title: string | null;
}

export interface ConfirmedByType {
  task: number;
  finance: number;
  food: number;
  calendar: number;
  note: number;
  journal: number;
  investment: number;
  other: number;
}

export interface DailyReview {
  review_date: string;
  timezone: string;
  captured_count: number;
  confirmed_count: number;
  rejected_count: number;
  pending_count: number;
  confirmed_by_type: ConfirmedByType;
  captured_items: CaptureSummary[];
  confirmed_items: InboxItemSummary[];
  rejected_items: InboxItemSummary[];
  pending_items: CaptureSummary[];
  summary: string;
}
