"""
Seeder functions for the chain app.
Provides programmatic and reusable database seeding for Blockchain and Account models.
"""

import logging
from typing import Optional, Tuple
from chain.models import Blockchain, BlockchainStatus

logger = logging.getLogger(__name__)


def seed_blockchain(
    *,
    name: str = "MYCOIN",
    symbol: str = "MYC",
    decimals: int = 8,
    chain_id: int = 1001,
    status: str = BlockchainStatus.ACTIVE,
    block_time_seconds: int = 5,
    max_block_gas: int = 30_000_000,
    min_gas_price: int = 1,
    base_transfer_gas: int = 21_000,
    min_validator_stake: Optional[int] = None,
    unbonding_blocks: int = 1_000,
    block_reward: Optional[int] = None,
    finality_numerator: int = 2,
    finality_denominator: int = 3,
) -> Tuple[Blockchain, bool]:
    """
    Idempotently seed or update the primary Blockchain configuration.

    Returns:
        Tuple[Blockchain, bool]: (blockchain instance, created boolean)
    """
    # 1 coin = 10**decimals smallest units
    multiplier = 10**decimals
    if min_validator_stake is None:
        min_validator_stake = 1_000 * multiplier  # 1,000 MYC
    if block_reward is None:
        block_reward = 5 * multiplier  # 5 MYC per block

    defaults = {
        "symbol": symbol.strip().upper(),
        "decimals": decimals,
        "blockTimeSeconds": block_time_seconds,
        "maxBlockGas": max_block_gas,
        "minGasPrice": min_gas_price,
        "baseTransferGas": base_transfer_gas,
        "minValidatorStake": min_validator_stake,
        "unbondingBlocks": unbonding_blocks,
        "blockReward": block_reward,
        "finalityNumerator": finality_numerator,
        "finalityDenominator": finality_denominator,
        "status": status,
    }

    # First attempt to find by unique name or chainId
    blockchain = Blockchain.objects.filter(name=name.strip()).first()
    if not blockchain:
        blockchain = Blockchain.objects.filter(chainId=chain_id).first()

    if blockchain:
        # Update existing record
        for field, value in defaults.items():
            setattr(blockchain, field, value)
        blockchain.name = name.strip()
        blockchain.chainId = chain_id
        blockchain.save()
        logger.info("Updated existing Blockchain: %s (chainId=%d)", blockchain.name, blockchain.chainId)
        return blockchain, False

    # Create new blockchain
    blockchain = Blockchain.objects.create(
        name=name.strip(),
        chainId=chain_id,
        **defaults,
    )
    logger.info("Created new Blockchain: %s (chainId=%d)", blockchain.name, blockchain.chainId)
    return blockchain, True

