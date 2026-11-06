"""
Health and basic diagnostic endpoints.
"""

from datetime import datetime, timezone
from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
async def get_health():
    """Returns basic health status of this running node instance."""
    return {
        "status": "healthy",
        "nodeId": settings.NODE_ID,
        "endpoint": settings.ENDPOINT,
        "protocolVersion": settings.PROTOCOL_VERSION,
        "chainId": settings.CHAIN_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

