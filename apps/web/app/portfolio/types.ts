export type QuoteStatus =
  | "live"
  | "delayed"
  | "stale"
  | "unavailable"
  | "unknown";

export type BrokerStatus =
  | "ok"
  | "auth_error"
  | "timeout"
  | "unavailable"
  | "malformed_response"
  | "not_configured"
  | "error";

export type PnlSource = "broker" | "calculated" | "unavailable";

export interface Position {
  broker: string;
  account_ref: string;
  instrument_id: string | null;
  symbol: string;
  asset_class: string | null;
  quantity: number;
  average_cost: number | null;
  currency: string;
  market_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  today_pnl: number | null;
  today_pnl_source: PnlSource;
  quote_status: QuoteStatus;
  as_of: string | null;
}

export interface CashBalance {
  broker: string;
  account_ref: string;
  currency: string;
  amount: number;
}

export interface AccountSummary {
  broker: string;
  account_ref: string;
  currency: string | null;
  net_liquidation: number | null;
  unrealized_pnl: number | null;
  today_pnl: number | null;
  today_pnl_source: PnlSource;
}

export interface CurrencyTotal {
  currency: string;
  market_value: number;
  market_value_complete: boolean;
  market_value_missing: number;
  unrealized_pnl: number | null;
  unrealized_pnl_complete: boolean;
  unrealized_pnl_missing: number;
}

export interface BrokerResult {
  broker: string;
  status: BrokerStatus;
  error: string | null;
  accounts: AccountSummary[];
  positions: Position[];
  cash: CashBalance[];
  as_of: string | null;
}

export interface Portfolio {
  brokers: BrokerResult[];
  totals_by_currency: CurrencyTotal[];
  generated_at: string;
  partial_failure: boolean;
}
