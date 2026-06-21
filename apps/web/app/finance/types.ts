export interface MoneyEvent {
  id: string;
  inbox_item_id: string;
  amount: number;
  currency: string;
  direction: string;
  merchant: string | null;
  category: string | null;
  occurred_at: string | null;
  notes: string | null;
  created_at: string;
}

export interface CategoryTotal {
  category: string;
  amount: number;
}

export interface CurrencyTotals {
  currency: string;
  total: number;
  by_category: CategoryTotal[];
}

export interface MoneyEventsResponse {
  items: MoneyEvent[];
  total: number;
  totals_by_currency: CurrencyTotals[];
}
