export interface CcyAmount {
  currency: string;
  amount: number;
}

export interface FocusTask {
  id: string;
  title: string | null;
  urgency: string | null;
  due_date: string | null;
}

export interface CalendarItem {
  id: string;
  title: string | null;
  proposed_datetime: string | null;
  location: string | null;
}

export interface DailyBriefing {
  kind: "daily";
  date: string;
  headline: string;
  focus: FocusTask[];
  calendar: CalendarItem[];
  spend_today: CcyAmount[];
  spend_month_to_date: CcyAmount[];
  portfolio_delta: CcyAmount[];
  pending_inbox: number;
  warnings: string[];
}

export interface BriefingResponse {
  timezone: string;
  briefing: DailyBriefing;
}
