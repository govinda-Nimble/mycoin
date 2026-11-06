"""
FastAPI application entry point for the MYC Blockchain Node.
"""

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.database.base import Base
from app.database.session import AsyncSessionLocal, engine
from app.api.routes import health, mempool, node, peer, transaction
from app.services.heartbeat_service import HeartbeatService
from app.services.node_service import NodeService

logging.basicConfig(
    level=logging.INFO,
    format=f"[%(asctime)s] [{settings.NODE_ID}] [%(levelname)s] %(message)s",
)
logger = logging.getLogger("myc_node")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    logger.info("Initializing %s on %s...", settings.NODE_ID, settings.ENDPOINT)

    # 1. Initialize database tables for this independent node database
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified for node %s", settings.NODE_ID)
    except Exception as exc:
        logger.error("Failed to verify/create database tables: %s", exc)

    # 2. Register or update local node state in its database
    try:
        async with AsyncSessionLocal() as session:
            await NodeService.init_or_update_local_node(session)
    except Exception as exc:
        logger.error("Failed to register node in database: %s", exc)

    # 3. Start periodic peer heartbeat monitor
    HeartbeatService.start(interval_seconds=settings.HEARTBEAT_INTERVAL_SECONDS)

    yield

    # 4. Graceful shutdown: Stop heartbeat and mark node as OFFLINE
    logger.info("Shutting down %s...", settings.NODE_ID)
    await HeartbeatService.stop()
    try:
        async with AsyncSessionLocal() as session:
            await NodeService.set_node_offline(session)
    except Exception as exc:
        logger.warning("Could not set node offline on shutdown: %s", exc)


def create_app() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title=f"MYC Blockchain Node ({settings.NODE_ID})",
        version=settings.PROTOCOL_VERSION,
        description="Independent MYC Blockchain Node simulation instance.",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(node.router, prefix="/api/v1")
    app.include_router(peer.router, prefix="/api/v1")
    app.include_router(transaction.router, prefix="/api/v1")
    app.include_router(mempool.router, prefix="/api/v1")

    @app.get("/", tags=["Root"])
    async def root():
        return {
            "message": "MYC Blockchain Node running",
            "nodeId": settings.NODE_ID,
            "endpoint": settings.ENDPOINT,
            "chainId": settings.CHAIN_ID,
            "docs": "/docs",
        }

    return app


app = create_app()
