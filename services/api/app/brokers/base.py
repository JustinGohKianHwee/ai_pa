"""
Broker adapter boundary.

Every adapter exposes the same synchronous, read-only operation: `fetch_portfolio()`
returning a normalised `BrokerResult`. Adapters catch their own errors and map them to a
`BrokerStatus` — they never raise broker secrets or raw payloads to the caller.

The orchestration layer (`portfolio_service`) runs each adapter in a bounded thread with
a per-broker timeout, so adapters can be plain blocking code.
"""
from abc import ABC, abstractmethod

from app.brokers.models import BrokerResult


class BrokerAdapter(ABC):
    #: Stable broker identifier used in responses, e.g. "tiger" or "ibkr".
    name: str

    @abstractmethod
    def fetch_portfolio(self) -> BrokerResult:
        """
        Fetch and normalise this broker's portfolio. Read-only. Must not raise for
        expected broker failures (auth, timeout, gateway down, malformed response,
        not configured) — those are returned as a `BrokerResult` with the matching
        `BrokerStatus`.
        """
        raise NotImplementedError
