"""
Deterministic Financial Intelligence metrics (Phase 22a) + monthly explanation (Phase 22b-1).

`compute_summary` and `compute_monthly` are PURE functions (no DB, no network) so every metric
is unit-testable. The route fetches + aggregates the raw inputs and passes them in. Rules:
  * Everything is per-currency. Amounts are NEVER summed across currencies.
  * Missing inputs yield None ("unavailable") — never a fabricated/estimated number.
  * Monthly expenses are "logged" expenses from confirmed money_events only (not total spend).
  * liquid_cash is non-broker cash (manual); broker cash/positions come from the portfolio
    snapshot's total_value — kept separate to avoid double counting in net worth.
"""
from decimal import Decimal
from typing import Optional


def _money(ccy: str, value: float) -> str:
    return f"{ccy} {value:,.2f}"


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


def _signed(ccy: str, delta: float) -> str:
    word = "up" if delta > 0 else "down" if delta < 0 else "unchanged"
    if delta == 0:
        return "unchanged"
    return f"{word} {_money(ccy, abs(delta))}"


def compute_monthly(
    month_label: str,
    prev_month_label: str,
    current_expenses: dict[str, float],
    previous_expenses: Optional[dict[str, float]],
    income: dict[str, float],
    manual_pair: Optional[tuple[dict, dict]],
    portfolio_pair: Optional[tuple[dict, dict]],
) -> dict:
    """
    Deterministic month-over-month explanation (Phase 22b-1), per currency.

    previous_expenses is None when there is no logged history before the current month
    (then previous/delta are unavailable — never implied as 0). income is the latest manual
    snapshot's monthly_income map. manual_pair / portfolio_pair are (latest, previous) rows,
    or None when fewer than two snapshots exist.
    """
    has_previous = previous_expenses is not None

    # Manual position = liquid_cash − liabilities, per currency, for each of the two snapshots.
    manual_pos: Optional[tuple[dict[str, float], dict[str, float], dict, dict]] = None
    if manual_pair is not None:
        latest, prev = manual_pair
        latest_pos = _to_map(latest.get("liquid_cash_json"))
        latest_liab = _to_map(latest.get("liabilities_json"))
        prev_pos = _to_map(prev.get("liquid_cash_json"))
        prev_liab = _to_map(prev.get("liabilities_json"))
        latest_net = {c: latest_pos.get(c, 0.0) - latest_liab.get(c, 0.0)
                      for c in set(latest_pos) | set(latest_liab)}
        prev_net = {c: prev_pos.get(c, 0.0) - prev_liab.get(c, 0.0)
                    for c in set(prev_pos) | set(prev_liab)}
        manual_pos = (latest_net, prev_net, latest, prev)

    # Portfolio total_value per currency for each of the two snapshots.
    pf_pair: Optional[tuple[dict[str, float], dict[str, float], dict, dict]] = None
    if portfolio_pair is not None:
        latest_s, prev_s = portfolio_pair
        latest_tv = {str(t["currency"]).strip().upper(): t["total_value"]
                     for t in (latest_s.get("currency_totals") or [])}
        prev_tv = {str(t["currency"]).strip().upper(): t["total_value"]
                   for t in (prev_s.get("currency_totals") or [])}
        pf_pair = (latest_tv, prev_tv, latest_s, prev_s)

    currencies = set(current_expenses) | set(income)
    if has_previous:
        currencies |= set(previous_expenses)
    if manual_pos:
        currencies |= set(manual_pos[0]) | set(manual_pos[1])
    if pf_pair:
        currencies |= set(pf_pair[0]) | set(pf_pair[1])

    blocks = []
    for c in sorted(currencies):
        cur_exp = current_expenses.get(c, 0.0)
        prev_exp = previous_expenses.get(c, 0.0) if has_previous else None
        exp_delta = (cur_exp - prev_exp) if prev_exp is not None else None

        income_c = income.get(c)
        cur_sr = (income_c - cur_exp) / income_c if income_c and income_c > 0 else None
        prev_sr = (
            (income_c - prev_exp) / income_c
            if income_c and income_c > 0 and prev_exp is not None
            else None
        )
        sr_delta = (cur_sr - prev_sr) if cur_sr is not None and prev_sr is not None else None

        manual_change = None
        if manual_pos is not None:
            latest_net, prev_net, latest_row, prev_row = manual_pos
            frm = prev_net.get(c, 0.0)
            to = latest_net.get(c, 0.0)
            manual_change = {
                "from": _round2(frm),
                "to": _round2(to),
                "delta": _round2(to - frm),
                "from_as_of": prev_row.get("as_of") or prev_row.get("created_at"),
                "to_as_of": latest_row.get("as_of") or latest_row.get("created_at"),
            }

        portfolio_change = None
        if pf_pair is not None:
            latest_tv, prev_tv, latest_s, prev_s = pf_pair
            if c in latest_tv and c in prev_tv:
                portfolio_change = {
                    "from": _round2(prev_tv[c]),
                    "to": _round2(latest_tv[c]),
                    "delta": _round2(latest_tv[c] - prev_tv[c]),
                    "from_date": str(prev_s.get("snapshot_date")),
                    "to_date": str(latest_s.get("snapshot_date")),
                    "partial": bool(latest_s.get("partial_failure") or prev_s.get("partial_failure")),
                }

        explanation: list[str] = []
        if prev_exp is not None:
            explanation.append(
                f"Logged spending in {month_label} was {_money(c, cur_exp)} — "
                f"{_signed(c, -exp_delta) if exp_delta is not None else ''} vs {prev_month_label} "
                f"({_money(c, prev_exp)}). Based on confirmed expense records only."
            )
        else:
            explanation.append(
                f"Logged spending in {month_label} was {_money(c, cur_exp)}. No prior month to "
                f"compare yet — based on confirmed expense records only."
            )
        if cur_sr is not None:
            line = (
                f"Logged savings rate in {month_label}: {cur_sr * 100:.1f}% "
                f"(income {_money(c, income_c)} − logged expenses {_money(c, cur_exp)})."
            )
            if prev_sr is not None:
                line += f" vs {prev_sr * 100:.1f}% in {prev_month_label}."
            explanation.append(line)
        else:
            explanation.append(
                f"Logged savings rate unavailable for {c} — add monthly income via a financial snapshot."
            )
        if manual_change is not None:
            explanation.append(
                f"Manual financial position (cash − liabilities) for {c} was "
                f"{_signed(c, manual_change['delta'])} between {manual_change['from_as_of']} and "
                f"{manual_change['to_as_of']}."
            )
        if portfolio_change is not None:
            note = " (partial — a broker was unavailable)" if portfolio_change["partial"] else ""
            explanation.append(
                f"Portfolio total for {c} was {_signed(c, portfolio_change['delta'])} between "
                f"{portfolio_change['from_date']} and {portfolio_change['to_date']}{note}."
            )

        blocks.append(
            {
                "currency": c,
                "logged_expenses": {
                    "current": _round2(cur_exp),
                    "previous": _round2(prev_exp) if prev_exp is not None else None,
                    "delta": _round2(exp_delta) if exp_delta is not None else None,
                },
                "savings_rate": {
                    "current": round(cur_sr, 4) if cur_sr is not None else None,
                    "previous": round(prev_sr, 4) if prev_sr is not None else None,
                    "delta": round(sr_delta, 4) if sr_delta is not None else None,
                },
                "manual_position_change": manual_change,
                "portfolio_change": portfolio_change,
                "explanation": explanation,
            }
        )

    return {
        "month": month_label,
        "prev_month": prev_month_label,
        "has_previous_month": has_previous,
        "currencies": blocks,
    }
