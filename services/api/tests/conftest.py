"""
Shared test fixtures.

`app.main` calls `load_dotenv(".env.local")` at import time, so importing the app (which
many tests do) pulls whatever is in the developer's real `.env.local` into the test
process environment. Once real broker credentials are present there, tests that assume an
unconfigured broker would otherwise see live creds and reach the real SDK/network.

The autouse fixture below clears all broker-related env vars before each test, so every
test starts from a known-empty broker configuration and sets only what it explicitly needs.
"""
import pytest

_BROKER_ENV_VARS = (
    "IBKR_ENABLED",
    "IBKR_CPAPI_BASE_URL",
    "IBKR_CPAPI_CACERT",
    "IBKR_ACCOUNT_LABEL",
    "TIGER_PROPS_PATH",
    "TIGER_ID",
    "TIGER_ACCOUNT",
    "TIGER_PRIVATE_KEY_PATH",
    "TIGER_ACCOUNT_LABEL",
    "PORTFOLIO_BROKER_TIMEOUT",
)


@pytest.fixture(autouse=True)
def _isolate_broker_env(monkeypatch):
    for var in _BROKER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
