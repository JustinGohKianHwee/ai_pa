"""
Read all environment variables for the AI Personal Assistant backend.

Nothing is instantiated here in Phase 1 — config is loaded by main.py at startup.
Supabase, Anthropic, and Telegram clients are initialised in later phases when
the respective features are built.
"""
import os

# Supabase — set in Phase 2 when the database schema is created
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY: str | None = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Anthropic (Claude) — set in Phase 6 when AI classification is built
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")

# OpenAI (Whisper) — set in Phase 10 when voice transcription is built
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

# Telegram — set in Phase 4 when the capture bot is built
TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET: str | None = os.getenv("TELEGRAM_WEBHOOK_SECRET")
TELEGRAM_USER_ID: str | None = os.getenv("TELEGRAM_USER_ID")

# Development security guard — required on all non-webhook routes (Phases 4–15)
DEV_ADMIN_TOKEN: str | None = os.getenv("DEV_ADMIN_TOKEN")
