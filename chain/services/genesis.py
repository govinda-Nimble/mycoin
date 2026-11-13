"""
Genesis initialization service for the blockchain.

Handles initial token supply configuration, deterministic system account creation,
genesis block creation, genesis allocation transaction records (audit trail),
and blockchain activation.

All operations execute inside an atomic transaction with concurrency safeguards.
"""

from dataclasses import dataclass
import hashlib
import logging
from typing import Dict, List, Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from common.models import GENESIS_PREVIOUS_HASH, ImmutableRecordError
from chain.models import (
    Account,
    AccountStatus,
    AccountType,
    Blockchain,
    BlockchainStatus,
    SystemAccountType,
)
from ledger.models import (
    Block,
    BlockStatus,
    BlockTransaction,
    EventType,
    ReceiptStatus,
    Transaction,
    TransactionEvent,
    TransactionReceipt,
    TransactionStatus,
    TransactionType,
)

logger = logging.getLogger(__name__)

# Deterministic addresses for system accounts (42 characters: '0x' + 40 lowercase hex)
GENESIS_MINT_ADDRESS = "0x0000000000000000000000000000000000000000"
TREASURY_ADDRESS = "0x0000000000000000000000000000000000000001"
VALIDATOR_RESERVE_ADDRESS = "0x0000000000000000000000000000000000000002"
DEVELOPMENT_RESERVE_ADDRESS = "0x0000000000000000000000000000000000000003"


class GenesisInitializationError(Exception):
    """Raised when blockchain genesis initialization fails or detects an inconsistent state."""
    pass


@dataclass(frozen=True)
class GenesisConfig:
    """Configuration for initial coin supply and allocations (in whole coins/tokens)."""

    chain_name: str = "MYCOIN"
    symbol: str = "MYC"
    chain_id: int = 1001
    decimals: int = 8
    initial_supply_tokens: int = 1_000_000
    treasury_tokens: int = 600_000
    validator_reserve_tokens: int = 300_000
    development_reserve_tokens: int = 100_000

    @property
    def multiplier(self) -> int:
        return 10 ** self.decimals

    @property
    def initial_supply_smallest_units(self) -> int:
        return self.initial_supply_tokens * self.multiplier

    @property
    def treasury_smallest_units(self) -> int:
        return self.treasury_tokens * self.multiplier

    @property
    def validator_reserve_smallest_units(self) -> int:
        return self.validator_reserve_tokens * self.multiplier

    @property
    def development_reserve_smallest_units(self) -> int:
        return self.development_reserve_tokens * self.multiplier

    def validate(self) -> None:
        """Validate configuration integrity before execution."""
        if self.decimals < 0 or self.decimals > 18:
            raise ValueError(f"Decimals must be between 0 and 18, got {self.decimals}")
        if self.chain_id <= 0:
            raise ValueError(f"Chain ID must be positive, got {self.chain_id}")
        if not self.chain_name.strip():
            raise ValueError("Chain name cannot be empty.")
        if not self.symbol.strip():
            raise ValueError("Symbol cannot be empty.")

        allocated = (
            self.treasury_tokens
            + self.validator_reserve_tokens
            + self.development_reserve_tokens
        )
        if allocated != self.initial_supply_tokens:
            raise ValueError(
                f"Sum of allocations ({allocated:,}) does not equal initial supply ({self.initial_supply_tokens:,})."
            )


@dataclass
class GenesisInitializationResult:
    """Result of genesis initialization containing blockchain and account state."""

    blockchain: Blockchain
    genesis_block: Block
    system_accounts: Dict[str, Account]
    total_supply_smallest_units: int
    already_initialized: bool = False
    message: str = ""

    @property
    def treasury_account(self) -> Optional[Account]:
        return self.system_accounts.get(SystemAccountType.TREASURY) or self.system_accounts.get("TREASURY")


def compute_merkle_root(tx_hashes: List[str]) -> str:
    """Compute binary SHA-256 Merkle root from transaction hashes."""
    if not tx_hashes:
        return hashlib.sha256(b"").hexdigest()
    current = list(tx_hashes)
    while len(current) > 1:
        next_level = []
        for i in range(0, len(current), 2):
            left = current[i]
            right = current[i + 1] if i + 1 < len(current) else left
            combined = hashlib.sha256((left + right).encode("utf-8")).hexdigest()
            next_level.append(combined)
        current = next_level
    return current[0]


def compute_state_root(accounts_state: Dict[str, int]) -> str:
    """Compute deterministic SHA-256 state root from account balances."""
    serialized = ",".join(f"{addr}:{bal}" for addr, bal in sorted(accounts_state.items()))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_block_hash(
    chain_id: int,
    height: int,
    previous_hash: str,
    merkle_root: str,
    state_root: str,
    timestamp_str: str,
) -> str:
    """Compute canonical block header SHA-256 hash."""
    header = f"{chain_id}:{height}:{previous_hash}:{merkle_root}:{state_root}:{timestamp_str}"
    return hashlib.sha256(header.encode("utf-8")).hexdigest()


def compute_tx_hash(
    chain_id: int,
    height: int,
    sender_address: str,
    receiver_address: str,
    amount: int,
    nonce: int,
) -> str:
    """Compute deterministic transaction hash."""
    payload = f"{chain_id}:{height}:{sender_address}:{receiver_address}:{amount}:{nonce}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def initialize_blockchain(config: Optional[GenesisConfig] = None) -> GenesisInitializationResult:
    """
    Idempotently initialize the blockchain with its initial coin supply and Genesis Block.

    - Validates supply configuration without floating point operations.
    - Creates or retrieves Blockchain record.
    - Creates deterministic system accounts (Treasury, Validator Reserve, Dev Reserve).
    - Allocates initial balances in smallest units.
    - Creates and audits genesis allocation transactions, receipts, and events.
    - Creates and finalizes Genesis Block at height 0.
    - Verifies total supply and marks Blockchain active.

    Returns:
        GenesisInitializationResult containing initialized records.
    """
    if config is None:
        config = GenesisConfig()
    config.validate()

    with transaction.atomic():
        # Retrieve or create Blockchain with row-level lock
        blockchain = Blockchain.objects.select_for_update().filter(chainId=config.chain_id).first()
        if not blockchain:
            blockchain = Blockchain.objects.select_for_update().filter(name=config.chain_name.strip()).first()

        if not blockchain:
            blockchain = Blockchain.objects.create(
                chainId=config.chain_id,
                name=config.chain_name.strip(),
                symbol=config.symbol.strip().upper(),
                decimals=config.decimals,
                status=BlockchainStatus.INITIALIZING,
            )
            logger.info("Created new Blockchain record '%s' (chain ID %d)", blockchain.name, blockchain.chainId)

        # Check for existing Genesis Block
        existing_genesis = Block.objects.filter(blockchain=blockchain, height=0).first()

        if existing_genesis:
            # Blockchain is already initialized or has a block at height 0; verify existing state
            return _verify_existing_genesis(blockchain, existing_genesis, config)

        # Ensure no partial/inconsistent blocks exist
        if Block.objects.filter(blockchain=blockchain).exists():
            raise GenesisInitializationError(
                f"Blockchain {blockchain.chainId} contains blocks but lacks a valid Genesis Block (height 0)."
            )

        # 1. Create or retrieve Genesis Mint (zero-address) Account
        genesis_mint, _ = Account.objects.get_or_create(
            blockchain=blockchain,
            address=GENESIS_MINT_ADDRESS,
            defaults={
                "accountType": AccountType.CONTRACT,
                "balance": 0,
                "nonce": 3,  # Executes 3 initial transfer transactions
                "status": AccountStatus.ACTIVE,
                "creationBlock": None,
            },
        )

        # 2. Create System Accounts with allocated balances
        allocations = [
            (SystemAccountType.TREASURY, TREASURY_ADDRESS, config.treasury_smallest_units),
            (SystemAccountType.VALIDATOR_RESERVE, VALIDATOR_RESERVE_ADDRESS, config.validator_reserve_smallest_units),
            (SystemAccountType.DEVELOPMENT_RESERVE, DEVELOPMENT_RESERVE_ADDRESS, config.development_reserve_smallest_units),
        ]

        system_accounts: Dict[str, Account] = {}
        for account_type, address, balance in allocations:
            acc, created = Account.objects.get_or_create(
                blockchain=blockchain,
                address=address,
                defaults={
                    "systemAccountType": account_type,
                    "accountType": AccountType.CONTRACT,
                    "balance": balance,
                    "nonce": 0,
                    "status": AccountStatus.ACTIVE,
                    "creationBlock": None,
                },
            )
            if not created and acc.systemAccountType != account_type:
                raise GenesisInitializationError(
                    f"Address collision: existing account at {address} has type {acc.systemAccountType}, expected {account_type}."
                )
            if not created and acc.balance != balance:
                raise GenesisInitializationError(
                    f"Account {account_type} ({address}) already exists with incorrect balance {acc.balance}; expected {balance}."
                )
            system_accounts[account_type] = acc

        # 3. Create Genesis Block in PROPOSED status
        now = timezone.now()
        timestamp_str = now.isoformat()

        # Compute initial state root
        accounts_state = {acc.address: acc.balance for acc in system_accounts.values()}
        accounts_state[GENESIS_MINT_ADDRESS] = 0
        state_root = compute_state_root(accounts_state)

        # Prepare 3 genesis transactions
        tx_specs = [
            (system_accounts[SystemAccountType.TREASURY], config.treasury_smallest_units, 0),
            (system_accounts[SystemAccountType.VALIDATOR_RESERVE], config.validator_reserve_smallest_units, 1),
            (system_accounts[SystemAccountType.DEVELOPMENT_RESERVE], config.development_reserve_smallest_units, 2),
        ]

        tx_hashes = [
            compute_tx_hash(blockchain.chainId, 0, GENESIS_MINT_ADDRESS, recipient.address, amount, nonce)
            for recipient, amount, nonce in tx_specs
        ]
        merkle_root = compute_merkle_root(tx_hashes)
        block_hash = compute_block_hash(
            blockchain.chainId,
            0,
            GENESIS_PREVIOUS_HASH,
            merkle_root,
            state_root,
            timestamp_str,
        )

        genesis_block = Block(
            blockchain=blockchain,
            height=0,
            blockHash=block_hash,
            parent=None,
            previousHash=GENESIS_PREVIOUS_HASH,
            merkleRoot=merkle_root,
            stateRoot=state_root,
            timestamp=now,
            proposer=None,
            status=BlockStatus.PROPOSED,
            transactionCount=len(tx_specs),
            gasUsed=0,
            blockReward=0,
            epoch=0,
            round=0,
        )
        genesis_block.full_clean()
        genesis_block.save()

        # 4. Create and link Transaction, BlockTransaction, TransactionReceipt, TransactionEvent
        for idx, (recipient, amount, nonce) in enumerate(tx_specs):
            tx_h = tx_hashes[idx]
            tx = Transaction(
                hash=tx_h,
                blockchain=blockchain,
                sender=genesis_mint,
                receiverAddress=recipient.address,
                receiver=recipient,
                txType=TransactionType.TRANSFER,
                amount=amount,
                nonce=nonce,
                gasLimit=blockchain.baseTransferGas,
                gasPrice=0,
                feePaid=0,
                signature="0" * 128,  # Valid hex signature placeholder for genesis
                publicKey="0" * 130,  # Valid hex public key placeholder for genesis
                status=TransactionStatus.FINALIZED,
                block=genesis_block,
            )
            tx.full_clean()
            tx.save()

            # Source-of-truth block membership
            btx = BlockTransaction(
                block=genesis_block,
                transaction=tx,
                txIndex=idx,
            )
            btx.full_clean()
            btx.save()

            # Transaction Receipt
            receipt = TransactionReceipt(
                transaction=tx,
                block=genesis_block,
                status=ReceiptStatus.SUCCESS,
                gasUsed=0,
                effectiveGasPrice=0,
                resultCode="GENESIS_ALLOCATION",
                resultMessage=f"Genesis initial allocation to {recipient.systemAccountType}",
            )
            receipt.full_clean()
            receipt.save()

            # Transaction Event
            event = TransactionEvent(
                transaction=tx,
                eventType=EventType.TRANSFER,
                eventIndex=0,
                eventData={
                    "allocationType": recipient.systemAccountType,
                    "amount": amount,
                    "recipientAddress": recipient.address,
                    "isGenesis": True,
                },
            )
            event.full_clean()
            event.save()

        # 5. Finalize Genesis Block (BlockTransaction rows cannot be added after this step)
        genesis_block.status = BlockStatus.FINALIZED
        genesis_block.finalizedAt = timezone.now()
        genesis_block.full_clean()
        genesis_block.save()

        # 6. Activate Blockchain and link finalized tip
        blockchain.latestFinalizedBlock = genesis_block
        blockchain.status = BlockchainStatus.ACTIVE
        blockchain.full_clean()
        blockchain.save()

        # 7. Final Supply Verification
        total_allocated = sum(acc.balance for acc in system_accounts.values())
        if total_allocated != config.initial_supply_smallest_units:
            raise GenesisInitializationError(
                f"Supply verification failed: allocated {total_allocated:,} != initial supply {config.initial_supply_smallest_units:,}"
            )

        logger.info(
            "Blockchain '%s' (chain %d) initialized successfully with initial supply %d",
            blockchain.name,
            blockchain.chainId,
            config.initial_supply_smallest_units,
        )

        return GenesisInitializationResult(
            blockchain=blockchain,
            genesis_block=genesis_block,
            system_accounts=system_accounts,
            total_supply_smallest_units=total_allocated,
            already_initialized=False,
            message="Blockchain initialized successfully.",
        )


def _verify_existing_genesis(
    blockchain: Blockchain,
    genesis_block: Block,
    config: GenesisConfig,
) -> GenesisInitializationResult:
    """Verify an already-initialized blockchain's state for idempotency and consistency."""
    # 1. Genesis block invariants
    if genesis_block.height != 0:
        raise GenesisInitializationError("Existing block at height 0 has invalid height.")
    if genesis_block.previousHash != GENESIS_PREVIOUS_HASH:
        raise GenesisInitializationError("Existing Genesis Block has invalid previous hash.")
    if genesis_block.status != BlockStatus.FINALIZED:
        raise GenesisInitializationError("Existing Genesis Block is not finalized.")
    if blockchain.latestFinalizedBlock_id != genesis_block.id:
        raise GenesisInitializationError("Blockchain latestFinalizedBlock does not reference the Genesis Block.")

    # 2. System accounts existence and balances
    expected_allocations = {
        SystemAccountType.TREASURY: (TREASURY_ADDRESS, config.treasury_smallest_units),
        SystemAccountType.VALIDATOR_RESERVE: (VALIDATOR_RESERVE_ADDRESS, config.validator_reserve_smallest_units),
        SystemAccountType.DEVELOPMENT_RESERVE: (DEVELOPMENT_RESERVE_ADDRESS, config.development_reserve_smallest_units),
    }

    system_accounts: Dict[str, Account] = {}
    for sys_type, (expected_addr, expected_balance) in expected_allocations.items():
        acc = Account.objects.filter(blockchain=blockchain, systemAccountType=sys_type).first()
        if not acc:
            raise GenesisInitializationError(f"Missing system account for {sys_type}.")
        if acc.address != expected_addr:
            raise GenesisInitializationError(f"System account {sys_type} has address {acc.address}, expected {expected_addr}.")
        if acc.balance != expected_balance:
            raise GenesisInitializationError(
                f"System account {sys_type} has balance {acc.balance}, expected {expected_balance}."
            )
        system_accounts[sys_type] = acc

    # 3. Supply verification
    total_allocated = sum(acc.balance for acc in system_accounts.values())
    if total_allocated != config.initial_supply_smallest_units:
        raise GenesisInitializationError(
            f"Supply mismatch on existing chain: allocated {total_allocated:,} != expected {config.initial_supply_smallest_units:,}."
        )

    # 4. Check block transaction count
    actual_tx_count = BlockTransaction.objects.filter(block=genesis_block).count()
    if actual_tx_count != 3:
        raise GenesisInitializationError(f"Genesis Block transaction count mismatch: found {actual_tx_count}, expected 3.")

    logger.info("Blockchain '%s' (chain %d) was already initialized; integrity verified.", blockchain.name, blockchain.chainId)

    return GenesisInitializationResult(
        blockchain=blockchain,
        genesis_block=genesis_block,
        system_accounts=system_accounts,
        total_supply_smallest_units=total_allocated,
        already_initialized=True,
        message="Blockchain has already been initialized and verified.",
    )

