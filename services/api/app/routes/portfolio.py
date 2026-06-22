"""
GET /portfolio — read-only portfolio aggregation across Tiger and IBKR (Phase 14).

Protected by Supabase owner authentication. Backend-only broker access; the browser never reaches the
brokers. No Supabase access, no writes of any kind. Brokers are fetched independently and
concurrently with bounded per-broker timeouts; one failing broker never hides the other.
"""
from fastapi import APIRouter, Depends

from app.brokers.models import PortfolioResponse
from app.brokers.portfolio_service import fetch_portfolio
from app.security import require_user

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio", dependencies=[Depends(require_user)])
async def get_portfolio() -> PortfolioResponse:
    return await fetch_portfolio()
