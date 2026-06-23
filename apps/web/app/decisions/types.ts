export type DecisionStatus = "active" | "reversed" | "archived";

export interface Decision {
  id: string;
  inbox_item_id: string;
  decision: string;
  reason: string | null;
  options_considered: string | null;
  expected_outcome: string | null;
  confidence: number | null;
  category: string | null;
  decided_at: string | null;
  status: DecisionStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface DecisionsResponse {
  items: Decision[];
  total: number;
}
