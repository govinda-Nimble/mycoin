"""
Node configuration management using Pydantic Settings.
Reads environment variables with fallback defaults.
"""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Node-specific runtime configuration.
    Each running node process overrides these via environment variables or .env files.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 1. Node Identity
    NODE_ID: str = "myc-node-001"
    NODE_TYPE: str = "FULL"  # "FULL" or "VALIDATOR"
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    ENDPOINT: str = "http://localhost:8001"

    # 2. Database Configuration (Each node MUST have its own independent database)
    DATABASE_URL: str = "sqlite+aiosqlite:///./myc_node_1.db"

    # 3. Blockchain Network Parameters
    CHAIN_ID: int = 1001
    PROTOCOL_VERSION: str = "v1.0.0"
    NETWORK_KEY: str = "myc-secret-network-key-2026"
    P2P_PUBLIC_KEY: str = (
        "04a1b2c3d4e5f67a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a"
        "2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d"
    )

    # 4. P2P & Monitoring Settings
    HEARTBEAT_INTERVAL_SECONDS: int = 5
    PEER_TIMEOUT_SECONDS: float = 3.0


# Global cached settings instance
settings = Settings()

