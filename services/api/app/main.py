from dotenv import load_dotenv

# Load .env.local from the working directory if present.
# Copy root .env.example → services/api/.env.local and fill in real values
# before Phase 2. No error is raised if the file does not exist yet.
load_dotenv(".env.local")

from fastapi import FastAPI  # noqa: E402 (import after dotenv so env is ready)
from app.routes.health import router as health_router  # noqa: E402

app = FastAPI(
    title="AI Personal Assistant API",
    description="Backend for the private AI personal operating system.",
    version="0.1.0",
)

app.include_router(health_router)
