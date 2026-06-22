"""
IBKR adapter — Client Portal Web API (CPAPI), read-only.

Talks to a locally running Client Portal Gateway over REST. Strictly GET-only: the single
network entry point `_request(method, path)` rejects any method or path not in an in-code
allowlist, so order/transfer endpoints are unreachable even by future code. No raw payloads
or gateway URLs are returned or logged.

TLS: the gateway serves a self-signed cert on loopback. Verification is resolved with a
strict precedence (CA bundle > loopback-only insecure > always verify). A generic
"disable verification" switch is never exposed.
"""
import ipaddress
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

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

DEFAULT_BASE_URL = "https://localhost:5000/v1/api"
_MAX_POSITION_PAGES = 10  # bound pagination to avoid unbounded loops

# GET-only allowlist. Each concrete request path must match one of these patterns, and the
# method must be GET. This is the ONLY place broker network access is permitted to widen.
_GET_ALLOWLIST = (
    re.compile(r"^/iserver/auth/status$"),
    re.compile(r"^/portfolio/accounts$"),
    re.compile(r"^/portfolio/[^/]+/summary$"),
    re.compile(r"^/portfolio/[^/]+/positions/\d+$"),
    re.compile(r"^/portfolio/[^/]+/ledger$"),
    re.compile(r"^/iserver/account/pnl/partitioned$"),
)


class IbkrAllowlistError(Exception):
    """Raised when a non-allowlisted (method, path) is attempted. Indicates a code bug."""


class IbkrConfigError(Exception):
    """Raised for an unsafe/invalid configuration (e.g. insecure TLS to a remote host)."""


def _enabled() -> bool:
    return (os.getenv("IBKR_ENABLED") or "").strip().lower() == "true"


def _base_url() -> str:
    return (os.getenv("IBKR_CPAPI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def _http_timeout() -> httpx.Timeout:
    # Internal timeout so the worker thread self-terminates near the per-broker budget,
    # not just the awaiter. Kept below PORTFOLIO_BROKER_TIMEOUT.
    try:
        budget = float(os.getenv("PORTFOLIO_BROKER_TIMEOUT") or "8")
    except ValueError:
        budget = 8.0
    read = max(2.0, budget * 0.8)
    return httpx.Timeout(connect=min(3.0, budget), read=read, write=3.0, pool=3.0)


def _is_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # Not a valid IP literal (e.g. "127.attacker.example") — not loopback.
        return False


def resolve_verify(base_url: str) -> Any:
    """
    Resolve the httpx `verify` argument with strict precedence:
      1. IBKR_CPAPI_CACERT set -> verify against that CA bundle/cert (path).
      2. else, only if the host is loopback -> verify=False (local gateway only).
      3. else -> always verify=True; a non-loopback host with no CA bundle is a config error.
    `verify=False` can never apply to a remote host.
    """
    cacert = (os.getenv("IBKR_CPAPI_CACERT") or "").strip()
    if cacert:
        if not os.path.isfile(cacert):
            # A non-file value is almost always a misconfiguration (e.g. an inline
            # comment leaked from .env). Fail clearly rather than handing a bad path
            # to the SSL layer, which raises a cryptic OSError.
            raise IbkrConfigError(
                "IBKR_CPAPI_CACERT is set but does not point to a readable file. "
                "Leave it blank for a local loopback gateway, or set it to the CA bundle path."
            )
        return cacert

    host = urlparse(base_url).hostname
    if _is_loopback(host):
        return False

    raise IbkrConfigError(
        "IBKR_CPAPI_BASE_URL is not loopback and IBKR_CPAPI_CACERT is unset; "
        "refusing to disable TLS verification for a remote host."
    )


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


class IbkrAdapter(BrokerAdapter):
    name = "ibkr"

    def _request(self, client: httpx.Client, method: str, path: str) -> httpx.Response:
        """The only network entry point. Enforces the GET-only path allowlist."""
        if method.upper() != "GET":
            raise IbkrAllowlistError(f"method not permitted: {method}")
        if not any(p.match(path) for p in _GET_ALLOWLIST):
            raise IbkrAllowlistError(f"path not permitted: {path}")
        resp = client.request(method.upper(), path)
        resp.raise_for_status()
        return resp

    def _get_json(self, client: httpx.Client, path: str) -> Any:
        return self._request(client, "GET", path).json()

    def fetch_portfolio(self) -> BrokerResult:
        if not _enabled():
            return BrokerResult(broker=self.name, status=BrokerStatus.NOT_CONFIGURED)

        base_url = _base_url()
        label = os.getenv("IBKR_ACCOUNT_LABEL")

        try:
            verify = resolve_verify(base_url)
        except IbkrConfigError:
            return BrokerResult(
                broker=self.name,
                status=BrokerStatus.ERROR,
                error="tls configuration error",
            )

        try:
            with httpx.Client(
                base_url=base_url,
                verify=verify,
                timeout=_http_timeout(),
                # Prevent proxy env vars (HTTP_PROXY etc.) redirecting local traffic.
                trust_env=False,
            ) as client:
                auth = self._get_json(client, "/iserver/auth/status")
                if not isinstance(auth, dict) or not auth.get("authenticated"):
                    return BrokerResult(
                        broker=self.name,
                        status=BrokerStatus.AUTH_ERROR,
                        error="not authenticated",
                    )

                accounts_raw = self._get_json(client, "/portfolio/accounts")
                if not isinstance(accounts_raw, list):
                    raise ValueError("accounts payload not a list")

                pnl_raw = self._get_json(client, "/iserver/account/pnl/partitioned")
                daily_by_acct = self._extract_daily_pnl(pnl_raw)

                accounts: list[AccountSummary] = []
                positions: list[Position] = []
                cash: list[CashBalance] = []

                for acct in accounts_raw:
                    acct_id = acct.get("accountId") or acct.get("id")
                    if not acct_id:
                        continue
                    # Always include the masked ID so each account_ref is unique even
                    # when multiple accounts share the same IBKR_ACCOUNT_LABEL.
                    masked = mask_account(str(acct_id))
                    ref = f"{label.strip()} / {masked}" if label and label.strip() else masked

                    summary_raw = self._get_json(client, f"/portfolio/{acct_id}/summary")
                    accounts.append(
                        self._normalize_summary(summary_raw, ref, daily_by_acct.get(acct_id))
                    )

                    positions.extend(self._fetch_positions(client, acct_id, ref))
                    cash.extend(self._fetch_cash(client, acct_id, ref))

            return BrokerResult(
                broker=self.name,
                status=BrokerStatus.OK,
                accounts=accounts,
                positions=positions,
                cash=cash,
                as_of=datetime.now(timezone.utc).isoformat(),
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403):
                return BrokerResult(
                    broker=self.name, status=BrokerStatus.AUTH_ERROR, error="not authenticated"
                )
            return BrokerResult(
                broker=self.name, status=BrokerStatus.UNAVAILABLE, error="gateway http error"
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return BrokerResult(
                broker=self.name, status=BrokerStatus.UNAVAILABLE, error="gateway unavailable"
            )
        except httpx.TimeoutException:
            return BrokerResult(broker=self.name, status=BrokerStatus.TIMEOUT, error="timeout")
        except (KeyError, ValueError, TypeError):
            return BrokerResult(
                broker=self.name,
                status=BrokerStatus.MALFORMED_RESPONSE,
                error="malformed broker response",
            )
        except Exception:
            return BrokerResult(broker=self.name, status=BrokerStatus.ERROR, error="error")

    # --- normalization helpers ------------------------------------------------

    def _fetch_positions(
        self, client: httpx.Client, acct_id: str, ref: str
    ) -> list[Position]:
        out: list[Position] = []
        for page in range(_MAX_POSITION_PAGES):
            rows = self._get_json(client, f"/portfolio/{acct_id}/positions/{page}")
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                out.append(self._normalize_position(row, ref))
            if len(rows) < 30:  # CPAPI page size; short page = last page
                break
        return out

    def _normalize_position(self, row: dict, ref: str) -> Position:
        price = _num(row.get("mktPrice"))
        conid = row.get("conid")
        return Position(
            broker=self.name,
            account_ref=ref,
            instrument_id=str(conid) if conid is not None else None,
            symbol=row.get("contractDesc") or row.get("ticker") or "—",
            asset_class=row.get("assetClass"),
            quantity=_num(row.get("position")) or 0.0,
            average_cost=_num(row.get("avgCost")),
            currency=row.get("currency") or "—",
            market_price=price,
            market_value=_num(row.get("mktValue")),
            unrealized_pnl=_num(row.get("unrealizedPnl")),
            today_pnl=None,  # not available per-position via CPAPI
            today_pnl_source=PnlSource.UNAVAILABLE,
            quote_status=QuoteStatus.UNKNOWN if price is not None else QuoteStatus.UNAVAILABLE,
        )

    def _fetch_cash(self, client: httpx.Client, acct_id: str, ref: str) -> list[CashBalance]:
        ledger = self._get_json(client, f"/portfolio/{acct_id}/ledger")
        out: list[CashBalance] = []
        if not isinstance(ledger, dict):
            return out
        for ccy, entry in ledger.items():
            if ccy == "BASE":  # pseudo-currency aggregate; skip to avoid double counting
                continue
            if not isinstance(entry, dict):
                continue
            amount = _num(entry.get("cashbalance"))
            if amount is None:
                continue
            out.append(
                CashBalance(broker=self.name, account_ref=ref, currency=ccy, amount=amount)
            )
        return out

    def _normalize_summary(
        self, summary_raw: Any, ref: str, daily_pnl: Optional[float]
    ) -> AccountSummary:
        nl = None
        ccy = None
        upnl = None
        if isinstance(summary_raw, dict):
            nl_entry = summary_raw.get("netliquidation")
            if isinstance(nl_entry, dict):
                nl = _num(nl_entry.get("amount"))
                ccy = nl_entry.get("currency")
            upnl_entry = summary_raw.get("unrealizedpnl")
            if isinstance(upnl_entry, dict):
                upnl = _num(upnl_entry.get("amount"))
        return AccountSummary(
            broker=self.name,
            account_ref=ref,
            currency=ccy,
            net_liquidation=nl,
            unrealized_pnl=upnl,
            today_pnl=daily_pnl,
            today_pnl_source=PnlSource.BROKER if daily_pnl is not None else PnlSource.UNAVAILABLE,
        )

    def _extract_daily_pnl(self, pnl_raw: Any) -> dict[str, float]:
        """
        Map account id -> broker-reported daily P&L (dpl) from /pnl/partitioned.
        Shape: {"upnl": {"<acctKey>": {"dpl": .., "upl": .., ...}}}. Keys are partitioned
        (e.g. "U1234567.Core"), so match by the account-id prefix.
        """
        out: dict[str, float] = {}
        if not isinstance(pnl_raw, dict):
            return out
        upnl = pnl_raw.get("upnl")
        if not isinstance(upnl, dict):
            return out
        for key, entry in upnl.items():
            if not isinstance(entry, dict):
                continue
            dpl = _num(entry.get("dpl"))
            if dpl is None:
                continue
            acct_id = key.split(".", 1)[0]
            out[acct_id] = dpl
        return out
