"""
Broker-neutral portfolio contract (Phase 14).

These Pydantic models are the only shape the frontend ever sees. Raw broker SDK
objects and REST payloads are normalised into these and never returned directly.

Design notes:
- Only fields a broker actually supplies (or that can be derived transparently) appear.
- Today's P&L carries an explicit source (`broker` / `calculated` / `unavailable`) so a
  derived value is never confused with a broker-reported one.
- Currency totals are grouped per currency and never summed across currencies (no FX).
  Completeness is tracked per metric so a subtotal is never presented as a full total.
- Account references are always masked; full account numbers never appear.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class QuoteStatus(str, Enum):
    LIVE = "live"
    DELAYED = "delayed"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class BrokerStatus(str, Enum):
    OK = "ok"
    AUTH_ERROR = "auth_error"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    MALFORMED_RESPONSE = "malformed_response"
    NOT_CONFIGURED = "not_configured"
    ERROR = "error"


class PnlSource(str, Enum):
    BROKER = "broker"
    CALCULATED = "calculated"
    UNAVAILABLE = "unavailable"


class Position(BaseModel):
    broker: str
    account_ref: str  # masked
    instrument_id: Optional[str] = None  # broker instrument id, e.g. IBKR conid
    symbol: str
    asset_class: Optional[str] = None
    quantity: float
    average_cost: Optional[float] = None
    currency: str
    market_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    today_pnl: Optional[float] = None
    today_pnl_source: PnlSource = PnlSource.UNAVAILABLE
    quote_status: QuoteStatus = QuoteStatus.UNKNOWN
    as_of: Optional[str] = None


class CashBalance(BaseModel):
    broker: str
    account_ref: str  # masked
    currency: str
    amount: float


class AccountSummary(BaseModel):
    broker: str
    account_ref: str  # masked
    currency: Optional[str] = None
    net_liquidation: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    today_pnl: Optional[float] = None
    today_pnl_source: PnlSource = PnlSource.UNAVAILABLE


class CurrencyTotal(BaseModel):
    """
    Totals for a single currency, summed across successful brokers. Currencies are
    never added together. Each metric carries its own completeness so a subtotal with
    missing inputs is never silently presented as a full total.
    """
    currency: str
    market_value: float = 0.0
    market_value_complete: bool = True
    market_value_missing: int = 0
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_complete: bool = True
    unrealized_pnl_missing: int = 0


class BrokerResult(BaseModel):
    broker: str
    status: BrokerStatus
    error: Optional[str] = None  # safe short label only — never secrets or raw responses
    accounts: list[AccountSummary] = []
    positions: list[Position] = []
    cash: list[CashBalance] = []
    as_of: Optional[str] = None  # fetch completion time (UTC ISO) = data freshness


class PortfolioResponse(BaseModel):
    brokers: list[BrokerResult]
    totals_by_currency: list[CurrencyTotal]
    generated_at: str
    partial_failure: bool
