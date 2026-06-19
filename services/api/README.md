# services/api — Backend API

**Status: Phase 1 scaffold complete.**

This directory contains the minimal FastAPI backend scaffold. Phase 1 exposes only
`GET /health`; no database client, writes, Telegram logic, or AI calls are implemented.

## Planned stack
- Python 3.11+
- FastAPI
- Supabase Python client
- Anthropic Python SDK (Claude)
- OpenAI Python SDK (Whisper, fallback)

## Role in the system
The backend is responsible for:
1. Receiving Telegram webhook events
2. Downloading and transcribing voice notes (Phase 10+)
3. Calling Claude to classify and extract structured data from raw captures
4. Writing classified items to the Supabase `inbox_items` table as pending records
5. Handling confirmation actions from the dashboard (writing confirmed domain records)
6. Running AI calls — page loads never trigger AI directly

The backend enforces the core pipeline:
**capture → classify/extract → pending inbox → (await review) → confirm → domain record**

## Scaffold completed in: Phase 1
