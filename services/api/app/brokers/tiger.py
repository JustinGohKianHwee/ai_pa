"""
Tiger adapter — official `tigeropen` SDK, read-only.

Calls only an allowlisted set of read methods (`get_positions`, `get_prime_assets` /
`get_assets`, `get_analytics_asset`). It never references any order/transfer method
(`place_order`, `modify_order`, `cancel_order`, …). The SDK is lazy-imported inside
`fetch_portfolio` so importing this module performs no network or SDK work.

Tiger exposes no real-time daily P&L, so today's P&L is derived from `get_analytics_asset`
(day-over-day) and labelled `PnlSource.CALCULATED`, distinct from broker-reported.
"""
import os
from datetime import datetime, timezone
from typing import Any, Optional

from app.brokers.base import BrokerAdapter
from app.brokers.masking import mask_account
from app.brokers.models import (
    AccountSummary,
    BrokerResult,
    BrokerStatus,
    CashBalance,
    PnlSource,
    Position,
    QuoteStatus,
)

# The only SDK methods this adapter is permitted to invoke. Order/transfer methods are
# intentionally absent and never referenced anywhere in this module.
ALLOWED_SDK_METHODS = frozenset(
    {"get_positions", "get_prime_assets", "get_assets", "get_analytics_asset"}
)


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from either a dict or an attribute-style object (SDK or test stub)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _creds() -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    return (
        (os.getenv("TIGER_ID") or "").strip() or None,
        (os.getenv("TIGER_ACCOUNT") or "").strip() or None,
        (os.getenv("TIGER_PRIVATE_KEY_PATH") or "").strip() or None,
        os.getenv("TIGER_ACCOUNT_LABEL"),
    )


def _classify_call_error(exc: Exception) -> BrokerStatus:
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg:
        return BrokerStatus.TIMEOUT
    if "auth" in name or any(
        k in msg
        for k in ("auth", "token", "sign", "permission", "login", "unauthorized", "forbidden")
    ):
        return BrokerStatus.AUTH_ERROR
    if any(k in msg for k in ("connect", "network", "unavailable", "refused", "unreachable")):
        return BrokerStatus.UNAVAILABLE
    return BrokerStatus.ERROR


class TigerAdapter(BrokerAdapter):
    name = "tiger"

    def fetch_portfolio(self) -> BrokerResult:
        tiger_id, account, key_path, label = _creds()
        if not (tiger_id and account and key_path):
            return BrokerResult(broker=self.name, status=BrokerStatus.NOT_CONFIGURED)

        try:
            trade_client = self._build_client(tiger_id, account, key_path)
        except ImportError:
            return BrokerResult(broker=self.name, status=BrokerStatus.NOT_CONFIGURED)
        except (OSError, FileNotFoundError):
            return BrokerResult(
                broker=self.name,
                status=BrokerStatus.NOT_CONFIGURED,
                error="private key unavailable",
            )
        except Exception:
            return BrokerResult(
                broker=self.name, status=BrokerStatus.ERROR, error="client init failed"
            )

        # Fetch phase — network calls via allowlisted SDK methods.
        try:
            positions_raw = trade_client.get_positions(account=account)
            assets_raw = self._load_assets(trade_client, account)
        except Exception as exc:
            return BrokerResult(
                broker=self.name, status=_classify_call_error(exc), error="broker call failed"
            )

        # Analytics is best-effort (calculated today P&L); never fails the whole broker.
        today_pnl = self._safe_analytics(trade_client, account)

        # Normalize phase — operate on returned objects only.
        ref = mask_account(account, label)
        try:
            positions = [self._normalize_position(p, ref) for p in (positions_raw or [])]
            cash, summary = self._normalize_assets(assets_raw, ref, today_pnl)
        except (AttributeError, KeyError, TypeError, ValueError, IndexError):
            return BrokerResult(
                broker=self.name,
                status=BrokerStatus.MALFORMED_RESPONSE,
                error="malformed broker response",
            )

        return BrokerResult(
            broker=self.name,
            status=BrokerStatus.OK,
            accounts=[summary],
            positions=positions,
            cash=cash,
            as_of=datetime.now(timezone.utc).isoformat(),
        )

    # --- SDK access -----------------------------------------------------------

    def _build_client(self, tiger_id: str, account: str, key_path: str) -> Any:
        """Lazy-import the SDK and construct a TradeClient. No network at import time."""
        from tigeropen.common.util.signature_utils import read_private_key
        from tigeropen.tiger_open_config import TigerOpenClientConfig
        from tigeropen.trade.trade_client import TradeClient

        config = TigerOpenClientConfig()
        config.private_key = read_private_key(key_path)
        config.tiger_id = tiger_id
        config.account = account
        # Best-effort SDK-level timeout (layer 1) where the installed version supports it.
        if hasattr(config, "timeout"):
            try:
                config.timeout = int(float(os.getenv("PORTFOLIO_BROKER_TIMEOUT") or "8"))
            except ValueError:
                pass
        return TradeClient(config)

    def _load_assets(self, trade_client: Any, account: str) -> Any:
        """Prefer prime-account assets; fall back to global `get_assets`."""
        try:
            return trade_client.get_prime_assets(account=account)
        except Exception:
            return trade_client.get_assets(account=account)

    def _safe_analytics(self, trade_client: Any, account: str) -> Optional[float]:
        try:
            analytics = trade_client.get_analytics_asset(account=account)
        except Exception:
            return None
        # Day-over-day P&L; tolerate dict, object, or single-element list shapes.
        if isinstance(analytics, list):
            analytics = analytics[0] if analytics else None
        return _num(_attr(analytics, "pnl"))

    # --- normalization --------------------------------------------------------

    def _normalize_position(self, p: Any, ref: str) -> Position:
        contract = _attr(p, "contract")
        price = _num(_attr(p, "market_price")) or _num(_attr(p, "latest_price"))
        identifier = _attr(contract, "identifier")
        return Position(
            broker=self.name,
            account_ref=ref,
            instrument_id=str(identifier) if identifier is not None else None,
            symbol=_attr(contract, "symbol") or "—",
            asset_class=_attr(contract, "sec_type"),
            quantity=_num(_attr(p, "quantity")) or 0.0,
            average_cost=_num(_attr(p, "average_cost")),
            currency=_attr(contract, "currency") or _attr(p, "currency") or "—",
            market_price=price,
            market_value=_num(_attr(p, "market_value")),
            unrealized_pnl=_num(_attr(p, "unrealized_pnl")),
            today_pnl=None,  # Tiger has no per-position daily P&L
            today_pnl_source=PnlSource.UNAVAILABLE,
            quote_status=QuoteStatus.UNKNOWN if price is not None else QuoteStatus.UNAVAILABLE,
        )

    def _normalize_assets(
        self, assets_raw: Any, ref: str, today_pnl: Optional[float]
    ) -> tuple[list[CashBalance], AccountSummary]:
        cash: list[CashBalance] = []
        net_liquidation: Optional[float] = None
        summary_ccy: Optional[str] = None
        unrealized: Optional[float] = None

        segments = _attr(assets_raw, "segments")
        if isinstance(segments, dict) and segments:
            # Prefer the securities segment ('S') for the headline summary figures.
            primary = segments.get("S") or next(iter(segments.values()))
            net_liquidation = _num(_attr(primary, "net_liquidation"))
            unrealized = _num(_attr(primary, "unrealized_pl"))
            summary_ccy = _attr(primary, "currency")
            for seg in segments.values():
                cash.extend(self._cash_from_currency_assets(seg, ref))
        else:
            # get_assets fallback shape: a list/obj carrying a summary.
            asset = assets_raw[0] if isinstance(assets_raw, list) and assets_raw else assets_raw
            summary = _attr(asset, "summary", asset)
            net_liquidation = _num(_attr(summary, "net_liquidation"))
            unrealized = _num(_attr(summary, "unrealized_pnl")) or _num(
                _attr(summary, "unrealized_pl")
            )
            summary_ccy = _attr(summary, "currency")
            cash.extend(self._cash_from_currency_assets(asset, ref))

        summary_model = AccountSummary(
            broker=self.name,
            account_ref=ref,
            currency=summary_ccy,
            net_liquidation=net_liquidation,
            unrealized_pnl=unrealized,
            today_pnl=today_pnl,
            today_pnl_source=PnlSource.CALCULATED
            if today_pnl is not None
            else PnlSource.UNAVAILABLE,
        )
        return cash, summary_model

    def _cash_from_currency_assets(self, container: Any, ref: str) -> list[CashBalance]:
        out: list[CashBalance] = []
        currency_assets = _attr(container, "currency_assets")
        if not isinstance(currency_assets, dict):
            return out
        for ccy, entry in currency_assets.items():
            amount = _num(_attr(entry, "cash_balance"))
            if amount is None:
                continue
            out.append(
                CashBalance(broker=self.name, account_ref=ref, currency=ccy, amount=amount)
            )
        return out
