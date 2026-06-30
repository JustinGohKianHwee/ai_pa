"""
Briefing & reflection assemblers (Phase 24) — pure, deterministic, unit-testable.

These functions take already-fetched structured data and return the briefing/reflection payloads.
They contain NO database access, NO I/O, and NO LLM calls: every fact is computed from the inputs,
and prose is templated. This honors the project's deterministic-first rule (numbers come from SQL,
never an LLM) and keeps synthesis on this side of the Phase 27 egress gate.

Currency rule: amounts are kept per-currency and NEVER summed across currencies.
"""
from typing import Optional

# Ordering for the "focus" list — the structured urgency field (free-text due_date is NOT parsed).
_URGENCY_ORDER = {"today": 0, "this_week": 1, "someday": 2}
_FOCUS_CAP = 5
_PENDING_INBOX_WARN_THRESHOLD = 10


def _fmt_ccy(by_ccy: dict) -> list[dict]:
    """Stable, sorted [{currency, amount}] list from a {currency: amount} map."""
    return [
        {"currency": c, "amount": round(float(a), 2)}
        for c, a in sorted(by_ccy.items())
    ]


def build_daily_briefing(
    today: str,
    open_tasks: list[dict],
    calendar_intents: list[dict],
    spend_today_by_ccy: dict,
    spend_mtd_by_ccy: dict,
    portfolio_delta_by_ccy: dict,
    pending_count: int,
    has_income_snapshot: bool,
) -> dict:
    """Assemble the forward-looking daily briefing from structured inputs.

    open_tasks: [{id,title,urgency,due_date,status}] (status='open' only, caller-filtered).
    calendar_intents: [{id,title,proposed_datetime,location}].
    *_by_ccy: {currency: amount}. portfolio_delta_by_ccy: latest-minus-previous snapshot total.
    """
    focus = sorted(
        ({"id": t.get("id"), "title": t.get("title"), "urgency": t.get("urgency"),
          "due_date": t.get("due_date")} for t in open_tasks),
        key=lambda t: _URGENCY_ORDER.get(t.get("urgency") or "", 9),
    )[:_FOCUS_CAP]

    urgent_today = [t for t in open_tasks if (t.get("urgency") == "today")]

    warnings: list[str] = []
    if urgent_today:
        n = len(urgent_today)
        warnings.append(f"{n} task{'s' if n != 1 else ''} marked for today.")
    if pending_count >= _PENDING_INBOX_WARN_THRESHOLD:
        warnings.append(f"{pending_count} items awaiting review in your inbox.")
    for c in sorted(portfolio_delta_by_ccy):
        d = portfolio_delta_by_ccy[c]
        if d is not None and d < 0:
            warnings.append(f"Portfolio down {abs(round(d, 2))} {c} since the last snapshot.")
    if not has_income_snapshot:
        warnings.append("No income snapshot logged — savings rate is unavailable.")

    open_n = len(open_tasks)
    cal_n = len(calendar_intents)
    headline_bits = []
    if open_n:
        headline_bits.append(f"{open_n} open task{'s' if open_n != 1 else ''}")
    if cal_n:
        headline_bits.append(f"{cal_n} calendar intent{'s' if cal_n != 1 else ''}")
    if pending_count:
        headline_bits.append(f"{pending_count} to review")
    headline = (
        "Today: " + ", ".join(headline_bits) + "." if headline_bits else "Nothing on today."
    )

    return {
        "kind": "daily",
        "date": today,
        "headline": headline,
        "focus": focus,
        "calendar": [
            {"id": c.get("id"), "title": c.get("title"),
             "proposed_datetime": c.get("proposed_datetime"), "location": c.get("location")}
            for c in calendar_intents
        ],
        "spend_today": _fmt_ccy(spend_today_by_ccy),
        "spend_month_to_date": _fmt_ccy(spend_mtd_by_ccy),
        "portfolio_delta": _fmt_ccy({c: v for c, v in portfolio_delta_by_ccy.items() if v is not None}),
        "pending_inbox": pending_count,
        "warnings": warnings,
    }


def _delta_strings(label: str, this_by_ccy: dict, prev_by_ccy: dict) -> list[str]:
    """Per-currency 'label X (▲/▼ Y vs last week)' strings. Never sums across currencies."""
    out: list[str] = []
    for c in sorted(set(this_by_ccy) | set(prev_by_ccy)):
        cur = round(float(this_by_ccy.get(c, 0.0)), 2)
        prev = round(float(prev_by_ccy.get(c, 0.0)), 2)
        diff = round(cur - prev, 2)
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "→")
        out.append(f"{label}: {cur} {c} ({arrow} {abs(diff)} vs last week)")
    return out


def build_weekly_reflection(
    week_start: str,
    week_end: str,
    confirmed_by_domain: dict,
    spend_week_by_ccy: dict,
    prev_week_spend_by_ccy: dict,
    exercise_count: int,
    food_count: int,
    active_goals: list[dict],
    portfolio_delta_week_by_ccy: dict,
) -> dict:
    """Assemble the weekly reflection: wins / concerns / trends / progress (all deterministic)."""
    total_confirmed = sum(confirmed_by_domain.values())

    wins: list[str] = []
    if exercise_count:
        wins.append(f"{exercise_count} workout{'s' if exercise_count != 1 else ''} logged.")
    if food_count:
        wins.append(f"{food_count} meal{'s' if food_count != 1 else ''} logged.")
    if total_confirmed:
        wins.append(f"{total_confirmed} item{'s' if total_confirmed != 1 else ''} confirmed across {len(confirmed_by_domain)} area(s).")

    concerns: list[str] = []
    for c in sorted(portfolio_delta_week_by_ccy):
        d = portfolio_delta_week_by_ccy[c]
        if d is not None and d < 0:
            concerns.append(f"Portfolio down {abs(round(d, 2))} {c} this week.")
    for c in sorted(set(spend_week_by_ccy) | set(prev_week_spend_by_ccy)):
        cur = round(float(spend_week_by_ccy.get(c, 0.0)), 2)
        prev = round(float(prev_week_spend_by_ccy.get(c, 0.0)), 2)
        if prev > 0 and cur > prev:
            concerns.append(f"Spending up {round(cur - prev, 2)} {c} vs last week.")

    trends = _delta_strings("Spend", spend_week_by_ccy, prev_week_spend_by_ccy)

    progress = [
        {"id": g.get("id"), "title": g.get("title"), "target": g.get("target"),
         "target_date": g.get("target_date")}
        for g in active_goals
    ]

    return {
        "kind": "weekly",
        "week_start": week_start,
        "week_end": week_end,
        "confirmed_by_domain": dict(sorted(confirmed_by_domain.items())),
        "spend_week": _fmt_ccy(spend_week_by_ccy),
        "spend_prev_week": _fmt_ccy(prev_week_spend_by_ccy),
        "portfolio_delta_week": _fmt_ccy(
            {c: v for c, v in portfolio_delta_week_by_ccy.items() if v is not None}
        ),
        "wins": wins,
        "concerns": concerns,
        "trends": trends,
        "progress": progress,
    }
