"""
Deterministic Financial Intelligence metrics (Phase 22a).

`compute_summary` is a PURE function (no DB, no network) so every metric is unit-testable.
The route fetches + aggregates the raw inputs and passes them in. Rules:
  * Everything is per-currency. Amounts are NEVER summed across currencies.
  * Missing inputs yield None ("unavailable") — never a fabricated/estimated number.
  * Monthly expenses are "logged" expenses from confirmed money_events only (not total spend).
  * liquid_cash is non-broker cash (manual); broker cash/positions come from the portfolio
    snapshot's total_value — kept separate to avoid double counting in net worth.
"""
from decimal import Decimal
from typing import Optional


def _round2(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def _to_map(entries) -> dict[str, float]:
    """[{currency, amount}, ...] → {CCY: amount} (summing any duplicate currencies)."""
    out: dict[str, Decimal] = {}
    for e in entries or []:
        ccy = str(e.get("currency", "")).strip().upper()
        if not ccy:
            continue
        try:
            amt = Decimal(str(e.get("amount")))
        except Exception:
            continue
        out[ccy] = out.get(ccy, Decimal("0")) + amt
    return {k: float(v) for k, v in out.items()}


def compute_summary(
    manual: Optional[dict],
    portfolio_totals: list[dict],
    current_month_expenses: dict[str, float],
    trailing_avg_expenses: dict[str, float],
) -> dict:
    """
    manual: latest manual_financial_snapshots row (or None).
    portfolio_totals: latest snapshot's per-currency totals (or []).
    current_month_expenses / trailing_avg_expenses: {CCY: amount} from confirmed money_events.
    """
    has_manual = manual is not None
    income = _to_map(manual.get("monthly_income_json")) if has_manual else {}
    investment = _to_map(manual.get("monthly_investment_json")) if has_manual else {}
    cash = _to_map(manual.get("liquid_cash_json")) if has_manual else {}
    liabilities = _to_map(manual.get("liabilities_json")) if has_manual else {}

    pf: dict[str, dict] = {}
    for t in portfolio_totals or []:
        pf[str(t["currency"]).strip().upper()] = t

    currencies = sorted(
        set(income) | set(investment) | set(cash) | set(liabilities)
        | set(pf) | set(current_month_expenses) | set(trailing_avg_expenses)
    )

    blocks = []
    for c in currencies:
        liquid_cash = cash.get(c) if has_manual else None
        liabilities_c = liabilities.get(c) if has_manual else None
        invested = pf[c]["invested_value"] if c in pf else None
        broker_total = pf[c]["total_value"] if c in pf else None
        income_c = income.get(c) if has_manual else None
        investment_c = investment.get(c) if has_manual else None
        expenses_c = current_month_expenses.get(c, 0.0)
        trailing_c = trailing_avg_expenses.get(c, 0.0)

        # Net worth = liquid_cash + broker_total - liabilities, from present components only.
        components = {
            "liquid_cash": liquid_cash,
            "broker_total": broker_total,
            "liabilities": liabilities_c,
        }
        missing = [k for k, v in components.items() if v is None]
        present_any = any(v is not None for v in components.values())
        nw_value = None
        if present_any:
            nw_value = (
                (liquid_cash or 0.0) + (broker_total or 0.0) - (liabilities_c or 0.0)
            )

        savings_rate = (
            (income_c - expenses_c) / income_c
            if income_c is not None and income_c > 0
            else None
        )
        investment_rate = (
            investment_c / income_c
            if income_c is not None and income_c > 0 and investment_c is not None
            else None
        )
        cash_runway_months = (
            liquid_cash / trailing_c
            if liquid_cash is not None and trailing_c > 0
            else None
        )

        portfolio_block = None
        if c in pf:
            t = pf[c]
            portfolio_block = {
                "market_value": _round2(t.get("market_value")),
                "cash_value": _round2(t.get("cash_value")),
                "invested_value": _round2(t.get("invested_value")),
                "total_value": _round2(t.get("total_value")),
                "complete": bool(t.get("market_value_complete", False)),
            }

        blocks.append(
            {
                "currency": c,
                "liquid_cash": _round2(liquid_cash),
                "invested": _round2(invested),
                "broker_total": _round2(broker_total),
                "liabilities": _round2(liabilities_c),
                "net_worth": {
                    "value": _round2(nw_value),
                    "complete": present_any and not missing,
                    "missing": missing,
                },
                "monthly_income": _round2(income_c),
                "monthly_investment": _round2(investment_c),
                "monthly_expenses_logged": _round2(expenses_c),
                "savings_rate": round(savings_rate, 4) if savings_rate is not None else None,
                "investment_rate": round(investment_rate, 4) if investment_rate is not None else None,
                "cash_runway_months": round(cash_runway_months, 1) if cash_runway_months is not None else None,
                "portfolio": portfolio_block,
            }
        )

    return {"currencies": blocks}
