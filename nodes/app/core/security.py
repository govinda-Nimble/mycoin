"""
Internal node-to-node security and authentication helpers.
Protects P2P endpoints from unauthorized public requests.
"""

from fastapi import Header, HTTPException, status
from app.core.config import settings


async def verify_network_key(x_network_key: str = Header(..., alias="X-Network-Key")):
    """
    Validates the shared network key for internal peer-to-peer endpoints.
    """
    if x_network_key != settings.NETWORK_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Network-Key header.",
        )
    return x_network_key

