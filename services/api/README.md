# services/api — Backend API

**Status: Not yet scaffolded. Reserved for Phase 1.**

This directory will contain the FastAPI Python backend service.

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

## Scaffold begins in: Phase 1
