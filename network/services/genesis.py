"""
Genesis initialization service re-exports for backward compatibility.
The authoritative implementation now resides in chain.services.genesis.
"""
from chain.services.genesis import (  # noqa: F401
    DEVELOPMENT_RESERVE_ADDRESS,
    GENESIS_MINT_ADDRESS,
    TREASURY_ADDRESS,
    VALIDATOR_RESERVE_ADDRESS,
    GenesisConfig,
    GenesisInitializationError,
    GenesisInitializationResult,
    initialize_blockchain,
)

__all__ = [
    "GENESIS_MINT_ADDRESS",
    "TREASURY_ADDRESS",
    "VALIDATOR_RESERVE_ADDRESS",
    "DEVELOPMENT_RESERVE_ADDRESS",
    "GenesisConfig",
    "GenesisInitializationResult",
    "GenesisInitializationError",
    "initialize_blockchain",
]
