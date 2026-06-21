from dotenv import load_dotenv

# Load .env.local from the working directory if present.
# Copy root .env.example → services/api/.env.local and fill in real values
# before using protected database routes. No error is raised if the file does not exist.
load_dotenv(".env.local")

from fastapi import FastAPI  # noqa: E402 (import after dotenv so env is ready)
from app.routes.calendar import router as calendar_router  # noqa: E402
from app.routes.classify import router as classify_router  # noqa: E402
from app.routes.finance import router as finance_router  # noqa: E402
from app.routes.food import router as food_router  # noqa: E402
from app.routes.health import router as health_router  # noqa: E402
from app.routes.health_db import router as health_db_router  # noqa: E402
from app.routes.inbox import router as inbox_router  # noqa: E402
from app.routes.review import router as review_router  # noqa: E402
from app.routes.tasks import router as tasks_router  # noqa: E402
from app.routes.telegram import router as telegram_router  # noqa: E402

app = FastAPI(
    title="AI Personal Assistant API",
    description="Backend for the private AI personal operating system.",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(health_db_router)
app.include_router(inbox_router)
app.include_router(classify_router)
app.include_router(review_router)
app.include_router(tasks_router)
app.include_router(finance_router)
app.include_router(food_router)
app.include_router(calendar_router)
app.include_router(telegram_router)
