"""
Read all environment variables for the AI Personal Assistant backend.

No external client is instantiated at import time. Supabase client creation begins in
Phase 3 and remains lazy; Phase 4 reads Telegram settings at request time. Anthropic and
OpenAI clients arrive in their later phases.
"""
import os

# Supabase — active from Phase 3; SERVICE_ROLE_KEY is server-side only
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY: str | None = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Anthropic (Claude) — set in Phase 6 when AI classification is built
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")

# OpenAI (Whisper) — set in Phase 10 when voice transcription is built
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

# Telegram — active from Phase 4; read at request time by the webhook
TELEGRAM_BOT_TOKEN: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET: str | None = os.getenv("TELEGRAM_WEBHOOK_SECRET")
TELEGRAM_USER_ID: str | None = os.getenv("TELEGRAM_USER_ID")

# Development security guard — required on all non-webhook routes (Phases 4–15)
DEV_ADMIN_TOKEN: str | None = os.getenv("DEV_ADMIN_TOKEN")
