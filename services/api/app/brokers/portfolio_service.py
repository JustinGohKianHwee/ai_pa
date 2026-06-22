"""
Portfolio orchestration (Phase 14).

Runs the broker adapters concurrently and independently, with bounded per-broker timeouts
and guards that prevent stuck broker calls from accumulating across refreshes:

1. Each adapter runs in a single module-level ThreadPoolExecutor (max_workers=2), so total
   broker worker threads can never exceed 2 regardless of request rate.
2. A per-broker in-flight tracker: if a broker's previous fetch is still running (genuinely
   hung past the timeout), a new request short-circuits to `unavailable` (busy) instead of
   submitting another job. Combined with (1) this guarantees at most one in-flight thread
   per broker.

`asyncio.wait_for` provides the per-broker timeout; `asyncio.shield` keeps the underlying
future tracked (and the thread accounted for) even after the awaiter times out.
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from app.brokers.base import BrokerAdapter
from app.brokers.ibkr import IbkrAdapter
from app.brokers.models import (
    BrokerResult,
    BrokerStatus,
    CurrencyTotal,
    PortfolioResponse,
)
from app.brokers.tiger import TigerAdapter

DEFAULT_TIMEOUT = 8.0

# Bounded executor: at most one worker per broker. Never grows with request rate.
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="broker")

# Per-broker in-flight future tracker for single-flight short-circuiting.
_INFLIGHT: dict[str, "asyncio.Future"] = {}


def _timeout() -> float:
    try:
        return float(os.getenv("PORTFOLIO_BROKER_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT


def _adapters() -> list[BrokerAdapter]:
    return [IbkrAdapter(), TigerAdapter()]


async def _run_adapter(adapter: BrokerAdapter, timeout: float) -> BrokerResult:
    name = adapter.name

    existing = _INFLIGHT.get(name)
    if existing is not None and not existing.done():
        # Previous fetch still running — do not pile up another thread.
        return BrokerResult(broker=name, status=BrokerStatus.UNAVAILABLE, error="busy")

    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_EXECUTOR, adapter.fetch_portfolio)
    _INFLIGHT[name] = future

    def _clear(fut: "asyncio.Future") -> None:
        if _INFLIGHT.get(name) is fut:
            _INFLIGHT.pop(name, None)

    future.add_done_callback(_clear)

    try:
        # shield: a wait_for timeout must not cancel the future, so the thread stays tracked.
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        return BrokerResult(broker=name, status=BrokerStatus.TIMEOUT, error="timeout")
    except Exception:
        return BrokerResult(broker=name, status=BrokerStatus.ERROR, error="error")


def _compute_totals(broker_results: list[BrokerResult]) -> list[CurrencyTotal]:
    """
    Sum market value and unrealized P&L per currency across SUCCESSFUL brokers only.
    Currencies are never added together. Completeness is tracked per metric so a subtotal
    with missing inputs is never presented as a full total.
    """
    by_ccy: dict[str, dict[str, object]] = {}
    for br in broker_results:
        if br.status != BrokerStatus.OK:
            continue
        for pos in br.positions:
            acc = by_ccy.setdefault(
                pos.currency,
                {"mv_sum": 0.0, "mv_missing": 0, "upnl_sum": 0.0, "upnl_present": 0, "upnl_missing": 0},
            )
            if pos.market_value is not None:
                acc["mv_sum"] = acc["mv_sum"] + pos.market_value  # type: ignore[operator]
            else:
                acc["mv_missing"] = acc["mv_missing"] + 1  # type: ignore[operator]
            if pos.unrealized_pnl is not None:
                acc["upnl_sum"] = acc["upnl_sum"] + pos.unrealized_pnl  # type: ignore[operator]
                acc["upnl_present"] = acc["upnl_present"] + 1  # type: ignore[operator]
            else:
                acc["upnl_missing"] = acc["upnl_missing"] + 1  # type: ignore[operator]

    totals: list[CurrencyTotal] = []
    for ccy in sorted(by_ccy):
        acc = by_ccy[ccy]
        mv_missing = int(acc["mv_missing"])  # type: ignore[arg-type]
        upnl_present = int(acc["upnl_present"])  # type: ignore[arg-type]
        upnl_missing = int(acc["upnl_missing"])  # type: ignore[arg-type]
        totals.append(
            CurrencyTotal(
                currency=ccy,
                market_value=float(acc["mv_sum"]),  # type: ignore[arg-type]
                market_value_complete=mv_missing == 0,
                market_value_missing=mv_missing,
                unrealized_pnl=float(acc["upnl_sum"]) if upnl_present else None,  # type: ignore[arg-type]
                unrealized_pnl_complete=upnl_missing == 0,
                unrealized_pnl_missing=upnl_missing,
            )
        )
    return totals


async def fetch_portfolio() -> PortfolioResponse:
    timeout = _timeout()
    adapters = _adapters()
    results = await asyncio.gather(
        *(_run_adapter(a, timeout) for a in adapters), return_exceptions=True
    )

    broker_results: list[BrokerResult] = []
    for adapter, result in zip(adapters, results):
        if isinstance(result, BrokerResult):
            broker_results.append(result)
        else:
            broker_results.append(
                BrokerResult(broker=adapter.name, status=BrokerStatus.ERROR, error="error")
            )

    totals = _compute_totals(broker_results)
    partial = any(br.status != BrokerStatus.OK for br in broker_results)

    return PortfolioResponse(
        brokers=broker_results,
        totals_by_currency=totals,
        generated_at=datetime.now(timezone.utc).isoformat(),
        partial_failure=partial,
    )
