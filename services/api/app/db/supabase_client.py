import os
from urllib.parse import urlparse

from supabase import Client, create_client


class SupabaseConfigurationError(ValueError):
    """Raised when required backend-only Supabase settings are missing."""


def get_supabase_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    missing = [name for name, val in [("SUPABASE_URL", url), ("SUPABASE_SERVICE_ROLE_KEY", key)] if not val]
    if missing:
        raise SupabaseConfigurationError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )

    assert url is not None and key is not None
    normalized_url = url.rstrip("/")
    parsed_url = urlparse(normalized_url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
        or parsed_url.path not in {"", "/"}
    ):
        raise SupabaseConfigurationError(
            "SUPABASE_URL must be the project base URL with no path"
        )

    return create_client(normalized_url, key)
