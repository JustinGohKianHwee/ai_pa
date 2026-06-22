"""
Shared test fixtures.

`app.main` calls `load_dotenv(".env.local")` at import time, so importing the app (which
many tests do) pulls whatever is in the developer's real `.env.local` into the test
process environment. Once real broker credentials are present there, tests that assume an
unconfigured broker would otherwise see live creds and reach the real SDK/network.

The autouse fixture below clears all broker-related env vars before each test, so every
test starts from a known-empty broker configuration and sets only what it explicitly needs.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

TEST_OWNER_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_KEY_ID = "phase-15a-test-key"
TEST_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
TEST_PUBLIC_KEY = TEST_PRIVATE_KEY.public_key()


def mint_test_token(
    *,
    sub: str = TEST_OWNER_USER_ID,
    private_key=TEST_PRIVATE_KEY,
    audience: str = "authenticated",
    expires_delta: timedelta = timedelta(hours=1),
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": sub,
            "aud": audience,
            "iat": now,
            "exp": now + expires_delta,
        },
        private_key,
        algorithm="ES256",
        headers={"kid": TEST_KEY_ID},
    )
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
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setenv("OWNER_USER_ID", TEST_OWNER_USER_ID)
    monkeypatch.setattr("app.security._get_signing_key", lambda token, url: TEST_PUBLIC_KEY)
    for var in _BROKER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def auth_header():
    def _header(**token_kwargs) -> dict[str, str]:
        return {"Authorization": f"Bearer {mint_test_token(**token_kwargs)}"}

    return _header
