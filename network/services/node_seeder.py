"""
Service to seed a Node with nodeType=VALIDATOR and status=ONLINE.

Ensures complete relational integrity, economic balance conservation, and ledger auditing:
1. Locates active Blockchain network configuration.
2. Creates or reuses validator operator User and active keystore Wallet.
3. Allocates required stake + operational buffer from VALIDATOR_RESERVE_ADDRESS (0x000...0002).
4. Creates a new Block at height parent.height + 1 containing the bootstrap funding Transaction.
5. Finalizes the Block and advances blockchain.latestFinalizedBlock.
6. Provisions the validator's on-chain EOA Account linked to this Block.
7. Seeds or updates Validator with ACTIVE status, activatedAt timestamp, and totalStake.
8. Seeds initial Stake record linked to the validator and funding Transaction.
9. Creates or updates Node record with nodeType=VALIDATOR, status=ONLINE, endpoint, and validator reference.

Strictly preserves total coin supply conservation:
Every unit allocated to the validator is deducted directly from VALIDATOR_RESERVE_ADDRESS.
All database operations execute atomically under Django transaction.atomic().
"""

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import logging
from typing import Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

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
from network.models import (
    Account,
    AccountStatus,
    AccountType,
    Blockchain,
    BlockchainStatus,
    Node,
    NodeStatus,
    NodeType,
)
from network.services.genesis import VALIDATOR_RESERVE_ADDRESS
from staking.models import Stake, StakeStatus, Validator, ValidatorStatus

from wallets.models import Wallet, WalletStatus, WalletType
from wallets.services.wallet_service import create_wallet_for_user, generate_keypair

logger = logging.getLogger(__name__)
User = get_user_model()


class NodeSeederError(Exception):
    """Raised when node seeding fails due to missing prerequisites or validation errors."""
    pass


@dataclass
class SeededNodeResult:
    """Result dataclass returned upon successful seeding of a Validator Node."""
    node: Node
    validator: Validator
    account: Account
    wallet: Wallet
    user: User
    funding_transaction: Optional[Transaction]
    funding_block: Optional[Block]
    created: bool
    message: str


def seed_validator_node(
    *,
    node_id: str = "myc-val-node-001",
    endpoint: str = "http://localhost:8001",
    operator_email: str = "validator@mycoin.network",
    stake_amount_myc: Optional[int] = None,
    commission_percent: Decimal = Decimal("5.00"),
    protocol_version: str = "v1.0.0",
    node_status: str = "ONLINE",
    chain_id: Optional[int] = None,
) -> SeededNodeResult:
    """
    Seed a Node configured as a VALIDATOR with status ONLINE.

    Transfers required stake funds from VALIDATOR_RESERVE_ADDRESS via a finalized
    ledger transaction and block, preserving exact total supply control.

    Args:
        node_id: Unique network identity for the node.
        endpoint: Communication host/URL endpoint for the node.
        operator_email: Email address for the validator operator account.
        stake_amount_myc: Staked amount in whole MYC tokens (defaults to blockchain minimum).
        commission_percent: Share of rewards retained by validator (0.00 - 100.00).
        protocol_version: Network protocol version string.
        node_status: Node operational status (defaults to ONLINE).
        chain_id: Optional specific chainId; if None, uses the active blockchain.

    Returns:
        SeededNodeResult containing all provisioned domain entities and ledger records.
    """
    clean_status = node_status.strip().upper()
    if clean_status not in NodeStatus.values:
        raise NodeSeederError(f"Invalid node status '{node_status}'. Choices are: {NodeStatus.values}")

    with transaction.atomic():
        # 1. Resolve active Blockchain
        if chain_id is not None:
            blockchain = Blockchain.objects.select_for_update().filter(chainId=chain_id).first()
        else:
            blockchain = Blockchain.objects.select_for_update().filter(status=BlockchainStatus.ACTIVE).first()

        if not blockchain:
            raise NodeSeederError(
                "No active blockchain found. Please initialize the blockchain first using: "
                "'python manage.py initialize_blockchain'"
            )

        decimals = blockchain.decimals
        multiplier = 10 ** decimals
        min_stake_units = blockchain.minValidatorStake

        if stake_amount_myc is not None:
            stake_units = stake_amount_myc * multiplier
            if stake_units < min_stake_units:
                raise NodeSeederError(
                    f"Stake amount ({stake_amount_myc:,} MYC) is below network minimum of "
                    f"{min_stake_units // multiplier:,} MYC."
                )
        else:
            stake_units = min_stake_units

        # Buffer of 100 MYC for operational gas fees
        operational_buffer_units = 100 * multiplier
        total_funding_units = stake_units + operational_buffer_units

        # 2. Operator User & Wallet
        clean_email = operator_email.strip().lower()
        operator = User.objects.filter(email=clean_email).first()
        if not operator:
            operator = User.objects.create_user(
                email=clean_email,
                firstName="Validator",
                lastName="Operator",
                userType="INDIVIDUAL",
                isEmailVerified=True,
            )
            logger.info("Created validator operator user '%s'", clean_email)

        wallet = Wallet.objects.filter(
            user=operator,
            status=WalletStatus.ACTIVE,
            address__in=Account.objects.filter(blockchain=blockchain).values_list("address", flat=True),
        ).first()
        
        if not wallet or Validator.objects.filter(publicKey=wallet.publicKey).exclude(account__blockchain=blockchain).exists():
            while True:
                private_key_hex, public_key_hex, address = generate_keypair()
                if not Wallet.objects.filter(address=address).exists() and not Validator.objects.filter(publicKey=public_key_hex).exists():
                    break
            wallet = Wallet.objects.create(
                user=operator,
                name=f"Validator {node_id} Wallet",
                walletType=WalletType.KEYSTORE,
                address=address,
                publicKey=public_key_hex,
                keyReference=private_key_hex,
                status=WalletStatus.ACTIVE,
            )
            logger.info("Created active keystore wallet '%s' for validator operator", wallet.address)

        # 3. Locate Validator Reserve Account
        reserve_account = Account.objects.select_for_update().filter(
            blockchain=blockchain,
            address=VALIDATOR_RESERVE_ADDRESS,
        ).first()

        if not reserve_account:
            raise NodeSeederError(
                f"Validator reserve account ({VALIDATOR_RESERVE_ADDRESS}) not found on blockchain '{blockchain.name}'. "
                "Ensure the genesis block has been initialized."
            )

        now = timezone.now()
        funding_tx: Optional[Transaction] = None
        funding_block: Optional[Block] = None

        # 4. Check if Account already exists and is sufficiently funded
        account = Account.objects.select_for_update().filter(blockchain=blockchain, address=wallet.address).first()

        if not account:
            # Verify reserve account has enough balance to fund this validator
            if reserve_account.balance < total_funding_units:
                raise NodeSeederError(
                    f"Validator reserve account ({VALIDATOR_RESERVE_ADDRESS}) has insufficient balance "
                    f"({reserve_account.balance:,} units) to fund validator with {total_funding_units:,} units."
                )

            # Resolve parent block
            blockchain.refresh_from_db()
            parent_block = blockchain.latestFinalizedBlock
            if not parent_block:
                parent_block = Block.objects.filter(
                    blockchain=blockchain,
                    status=BlockStatus.FINALIZED,
                ).order_by("-height").first()

            if not parent_block:
                raise NodeSeederError("Blockchain has no finalized genesis block.")

            new_height = parent_block.height + 1

            # Create Account record with 0 balance first
            account = Account.objects.create(
                blockchain=blockchain,
                address=wallet.address,
                accountType=AccountType.EOA,
                balance=0,
                nonce=0,
                status=AccountStatus.ACTIVE,
            )

            # Create Validator record
            validator = Validator.objects.filter(account=account).first()
            if not validator:
                validator = Validator.objects.create(
                    account=account,
                    publicKey=wallet.publicKey,
                    status=ValidatorStatus.ACTIVE,
                    totalStake=stake_units,
                    commissionPercent=commission_percent,
                    activatedAt=now,
                    lastActiveAt=now,
                )
            else:
                validator.status = ValidatorStatus.ACTIVE
                validator.totalStake = stake_units
                validator.activatedAt = validator.activatedAt or now
                validator.lastActiveAt = now
                validator.save()

            # Create Block in PROPOSED status with this validator as proposer
            timestamp_str = now.isoformat()
            reserve_nonce = reserve_account.nonce

            tx_hash = hashlib.sha256(
                f"{blockchain.chainId}:{new_height}:{VALIDATOR_RESERVE_ADDRESS}:{account.address}:{total_funding_units}:{reserve_nonce}".encode("utf-8")
            ).hexdigest().lower()

            merkle_root = hashlib.sha256(tx_hash.encode("utf-8")).hexdigest().lower()
            state_root = hashlib.sha256(
                f"{VALIDATOR_RESERVE_ADDRESS}:{reserve_account.balance - total_funding_units},{account.address}:{total_funding_units}".encode("utf-8")
            ).hexdigest().lower()

            block_hash = hashlib.sha256(
                f"{blockchain.chainId}:{new_height}:{parent_block.blockHash}:{merkle_root}:{state_root}:{timestamp_str}".encode("utf-8")
            ).hexdigest().lower()

            funding_block = Block(
                blockchain=blockchain,
                height=new_height,
                blockHash=block_hash,
                parent=parent_block,
                previousHash=parent_block.blockHash,
                merkleRoot=merkle_root,
                stateRoot=state_root,
                timestamp=now,
                proposer=validator,
                status=BlockStatus.PROPOSED,
                transactionCount=1,
                gasUsed=0,
                blockReward=0,
                epoch=0,
                round=0,
                proposerSignature="0" * 128,
            )
            funding_block.full_clean()
            funding_block.save()

            # Deduct from Validator Reserve Account
            reserve_account.balance -= total_funding_units
            reserve_account.nonce += 1
            reserve_account.save(update_fields=["balance", "nonce", "updatedAt"])

            # Credit Validator Account and assign creationBlock
            account.balance = total_funding_units
            account.creationBlock = funding_block
            account.save(update_fields=["balance", "creationBlock", "updatedAt"])

            # Create Transaction
            funding_tx = Transaction(
                hash=tx_hash,
                blockchain=blockchain,
                sender=reserve_account,
                receiverAddress=account.address,
                receiver=account,
                txType=TransactionType.TRANSFER,
                amount=total_funding_units,
                nonce=reserve_nonce,
                gasLimit=blockchain.baseTransferGas,
                gasPrice=0,
                feePaid=0,
                signature="0" * 128,
                publicKey="0" * 130,
                status=TransactionStatus.FINALIZED,
                block=funding_block,
            )
            funding_tx.full_clean()
            funding_tx.save()

            # BlockTransaction
            btx = BlockTransaction(
                block=funding_block,
                transaction=funding_tx,
                txIndex=0,
            )
            btx.full_clean()
            btx.save()

            # TransactionReceipt & Event
            receipt = TransactionReceipt(
                transaction=funding_tx,
                block=funding_block,
                status=ReceiptStatus.SUCCESS,
                gasUsed=0,
                effectiveGasPrice=0,
                resultCode="VALIDATOR_BOOTSTRAP",
                resultMessage=f"Validator bootstrap funding from {reserve_account.systemAccountType} to {account.address}",
            )
            receipt.full_clean()
            receipt.save()

            event = TransactionEvent(
                transaction=funding_tx,
                eventType=EventType.TRANSFER,
                eventIndex=0,
                eventData={
                    "allocationType": "VALIDATOR_BOOTSTRAP",
                    "amount": total_funding_units,
                    "recipientAddress": account.address,
                    "senderAddress": reserve_account.address,
                },
            )
            event.full_clean()
            event.save()

            # Finalize Block and update Blockchain tip
            funding_block.status = BlockStatus.FINALIZED
            funding_block.finalizedAt = timezone.now()
            funding_block.full_clean()
            funding_block.save()

            blockchain.latestFinalizedBlock = funding_block
            blockchain.full_clean()
            blockchain.save(update_fields=["latestFinalizedBlock", "updatedAt"])

            logger.info(
                "Transferred %d units from Validator Reserve to %s in Block #%d (Tx: %s)",
                total_funding_units,
                account.address,
                new_height,
                tx_hash[:12],
            )
        else:
            # Account already exists; retrieve existing validator
            validator = Validator.objects.filter(account=account).first()
            if not validator:
                validator = Validator.objects.create(
                    account=account,
                    publicKey=wallet.publicKey,
                    status=ValidatorStatus.ACTIVE,
                    totalStake=stake_units,
                    commissionPercent=commission_percent,
                    activatedAt=now,
                    lastActiveAt=now,
                )
            else:
                validator.status = ValidatorStatus.ACTIVE
                validator.totalStake = max(validator.totalStake, stake_units)
                validator.activatedAt = validator.activatedAt or now
                validator.lastActiveAt = now
                validator.save()

        # 5. Stake Record: ensure active stake exists
        stake = Stake.objects.filter(validator=validator, stakerAccount=account, status=StakeStatus.ACTIVE).first()
        if not stake:
            height = blockchain.latestFinalizedBlock.height if blockchain.latestFinalizedBlock else 0
            stake = Stake.objects.create(
                validator=validator,
                stakerAccount=account,
                amount=stake_units,
                status=StakeStatus.ACTIVE,
                stakedAtHeight=height,
                stakedAt=now,
                stakeTransaction=funding_tx,
            )
            logger.info("Created Stake record for validator %s with amount %d", validator.id, stake_units)

        # 6. Node Record: fetch, update, or create
        node_created = False
        node = Node.objects.filter(nodeId=node_id).first()
        if not node:
            node = Node.objects.filter(blockchain=blockchain, endpoint=endpoint).first()

        if node:
            node.nodeId = node_id
            node.nodeType = NodeType.VALIDATOR
            node.endpoint = endpoint
            node.status = clean_status
            node.validator = validator
            node.p2pPublicKey = wallet.publicKey
            node.protocolVersion = protocol_version
            node.lastHeartbeat = now
            node.full_clean()
            node.save()
            logger.info("Updated existing Node '%s' to VALIDATOR with status %s", node_id, clean_status)
            message = f"Node '{node_id}' updated successfully (nodeType=VALIDATOR, status={clean_status})."
        else:
            node = Node.objects.create(
                blockchain=blockchain,
                nodeId=node_id,
                nodeType=NodeType.VALIDATOR,
                endpoint=endpoint,
                status=clean_status,
                lastHeartbeat=now,
                protocolVersion=protocol_version,
                p2pPublicKey=wallet.publicKey,
                validator=validator,
            )
            node.full_clean()
            node_created = True
            logger.info("Created new Node '%s' (nodeType=VALIDATOR, status=%s)", node_id, clean_status)
            message = f"Node '{node_id}' created successfully (nodeType=VALIDATOR, status={clean_status})."

        return SeededNodeResult(
            node=node,
            validator=validator,
            account=account,
            wallet=wallet,
            user=operator,
            funding_transaction=funding_tx,
            funding_block=funding_block,
            created=node_created,
            message=message,
        )
