export interface SnapshotCurrencyTotal {
  currency: string;
  market_value: number;
  cash_value: number;
  invested_value: number;
  total_value: number;
  market_value_complete: boolean;
  market_value_missing: number;
}

export interface SnapshotSummary {
  snapshot_date: string;
  partial_failure: boolean;
  currency_totals: SnapshotCurrencyTotal[];
}

export interface SnapshotListResponse {
  items: SnapshotSummary[];
  total: number;
}

export interface SnapshotPosition {
  broker: string;
  account_ref: string;
  stable_asset_id: string;
  asset_symbol: string;
  asset_name: string | null;
  asset_type: string;
  instrument_id: string | null;
  quantity: number | null;
  price: number | null;
  market_value: number | null;
  average_cost: number | null;
  cost_basis: number | null;
  unrealized_pnl: number | null;
  today_pnl: number | null;
  currency: string;
  allocation_pct: number | null;
  quote_status: string | null;
  metadata_json: Record<string, unknown>;
}

export interface SnapshotDetail {
  snapshot_date: string;
  generated_at: string;
  source: string;
  partial_failure: boolean;
  broker_status_json: Record<string, string>;
  currency_totals: SnapshotCurrencyTotal[];
  positions: SnapshotPosition[];
}
