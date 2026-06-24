export interface PortfolioBlock {
  market_value: number | null;
  cash_value: number | null;
  invested_value: number | null;
  total_value: number | null;
  complete: boolean;
}

export interface CurrencyBlock {
  currency: string;
  liquid_cash: number | null;
  invested: number | null;
  broker_total: number | null;
  liabilities: number | null;
  net_worth: { value: number | null; complete: boolean; missing: string[] };
  monthly_income: number | null;
  monthly_investment: number | null;
  monthly_expenses_logged: number | null;
  savings_rate: number | null;
  investment_rate: number | null;
  cash_runway_months: number | null;
  portfolio: PortfolioBlock | null;
}

export interface FinancialSummary {
  currencies: CurrencyBlock[];
  portfolio_as_of: string | null;
  portfolio_partial: boolean | null;
  manual_as_of: string | null;
  has_manual_snapshot: boolean;
}

export interface FinancialGoalProgress {
  id: string;
  title: string;
  target_value: number;
  target_currency: string;
  target_metric: string;
  base_value: number | null;
  progress_pct: number | null;
  status: string;
}

export interface FinancialGoalsResponse {
  items: FinancialGoalProgress[];
  portfolio_as_of: string | null;
  portfolio_partial: boolean | null;
}
