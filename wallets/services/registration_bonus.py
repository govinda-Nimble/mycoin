"""
Registration bonus service.

Provisions an on-chain Account for a newly registered user,
transfers 100 MYC from TREASURY_ADDRESS as a registration bonus,
creates a finalized REG_BONUS Transaction and single-transaction Block,
and advances the blockchain tip.
"""

from dataclasses import dataclass
import hashlib
import logging
from typing import Any, Optional

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
from network.models import Account, AccountStatus, AccountType, Blockchain, BlockchainStatus
from network.services.genesis import TREASURY_ADDRESS
from staking.models import Validator
from wallets.models import Wallet

logger = logging.getLogger(__name__)

# Configurable registration bonus amount in whole MYC coins
REGISTRATION_BONUS_MYC: int = 100


@dataclass
class RegistrationBonusResult:
    """Encapsulates records provisioned during the registration bonus process."""
    account: Account
    transaction: Transaction
    block: Block
    bonus_units: int
    bonus_myc: int


def create_account_and_grant_registration_bonus(
    *,
    user: Any,
    wallet: Wallet,
    bonus_myc: int = REGISTRATION_BONUS_MYC,
) -> Optional[RegistrationBonusResult]:
    """
    Idempotently creates an on-chain Account for the user's wallet,
    allocates 100 MYC registration bonus from Treasury,
    records a finalized REG_BONUS transaction inside a newly finalized Block,
    and updates the active blockchain's latest finalized block.

    Args:
        user: The newly registered User instance.
        wallet: The user's active keystore Wallet instance.
        bonus_myc: Bonus amount in whole MYC tokens (default: 100).

    Returns:
        RegistrationBonusResult containing provisioned account, transaction, and block;
        or None if no active blockchain exists.
    """
    with transaction.atomic():
        # 1. Locate active blockchain
        blockchain = Blockchain.objects.select_for_update().filter(
            status=BlockchainStatus.ACTIVE
        ).first()

        if not blockchain:
            logger.warning("No active blockchain found. Skipping registration bonus account provisioning.")
            return None

        # 2. Check if user already has an Account on this blockchain
        existing_account = Account.objects.filter(blockchain=blockchain, address=wallet.address).first()
        if existing_account:
            logger.info("User %s already has on-chain account %s.", user.email, existing_account.address)
            # Find the transaction that granted the bonus if exists
            bonus_tx = Transaction.objects.filter(
                blockchain=blockchain,
                receiver=existing_account,
                txType=TransactionType.REG_BONUS,
            ).first()
            creation_blk = existing_account.creationBlock or (bonus_tx.block if bonus_tx else None)
            multiplier = 10 ** blockchain.decimals
            return RegistrationBonusResult(
                account=existing_account,
                transaction=bonus_tx,
                block=creation_blk,
                bonus_units=existing_account.balance,
                bonus_myc=existing_account.balance // multiplier,
            )

        # 3. Locate Treasury Account
        treasury_account = Account.objects.select_for_update().filter(
            blockchain=blockchain,
            address=TREASURY_ADDRESS,
        ).first()

        if not treasury_account:
            raise ValueError(f"Treasury account ({TREASURY_ADDRESS}) not found on blockchain '{blockchain.name}'.")

        multiplier = 10 ** blockchain.decimals
        bonus_units = bonus_myc * multiplier

        if treasury_account.balance < bonus_units:
            raise ValueError(
                f"Treasury account balance ({treasury_account.balance:,}) is insufficient "
                f"for {bonus_myc} MYC registration bonus ({bonus_units:,} units)."
            )

        # 4. Look up an active validator for block proposal
        proposer_validator = Validator.objects.filter(
            account__blockchain=blockchain,
            status="ACTIVE",
        ).first()

        if not proposer_validator:
            from network.services.node_seeder import seed_validator_node
            seed_res = seed_validator_node(node_id="myc-val-001", node_status="ONLINE")
            proposer_validator = seed_res.validator
            blockchain.refresh_from_db()
            treasury_account.refresh_from_db()

        # Resolve parent block and new height
        parent_block = blockchain.latestFinalizedBlock
        if not parent_block:
            parent_block = Block.objects.filter(
                blockchain=blockchain,
                height=0,
                status=BlockStatus.FINALIZED,
            ).first()

        if not parent_block:
            raise ValueError(f"Blockchain '{blockchain.name}' has no finalized tip or genesis block.")

        new_height = parent_block.height + 1

        # 5. Prepare deterministic hashes and roots
        now = timezone.now()
        timestamp_str = now.isoformat()
        treasury_nonce = treasury_account.nonce

        tx_hash = hashlib.sha256(
            f"{blockchain.chainId}:{new_height}:{TREASURY_ADDRESS}:{wallet.address}:{bonus_units}:{treasury_nonce}".encode("utf-8")
        ).hexdigest().lower()

        merkle_root = hashlib.sha256(tx_hash.encode("utf-8")).hexdigest().lower()
        state_root = hashlib.sha256(
            f"{TREASURY_ADDRESS}:{treasury_account.balance - bonus_units},{wallet.address}:{bonus_units}".encode("utf-8")
        ).hexdigest().lower()

        block_hash = hashlib.sha256(
            f"{blockchain.chainId}:{new_height}:{parent_block.blockHash}:{merkle_root}:{state_root}:{timestamp_str}".encode("utf-8")
        ).hexdigest().lower()

        # 6. Create Block in PROPOSED status
        new_block = Block(
            blockchain=blockchain,
            height=new_height,
            blockHash=block_hash,
            parent=parent_block,
            previousHash=parent_block.blockHash,
            merkleRoot=merkle_root,
            stateRoot=state_root,
            timestamp=now,
            proposer=proposer_validator,
            status=BlockStatus.PROPOSED,
            transactionCount=1,
            gasUsed=0,
            blockReward=0,
            epoch=0,
            round=0,
            proposerSignature="0" * 128,
        )
        new_block.full_clean()
        new_block.save()

        # 7. Create User Account linked to this Block
        user_account = Account(
            blockchain=blockchain,
            address=wallet.address,
            accountType=AccountType.EOA,
            balance=bonus_units,
            nonce=0,
            status=AccountStatus.ACTIVE,
            creationBlock=new_block,
        )
        user_account.full_clean()
        user_account.save()

        # 8. Deduct from Treasury Account
        treasury_account.balance -= bonus_units
        treasury_account.nonce += 1
        treasury_account.save(update_fields=["balance", "nonce", "updatedAt"])

        # 9. Create REG_BONUS Transaction
        tx = Transaction(
            hash=tx_hash,
            blockchain=blockchain,
            sender=treasury_account,
            receiverAddress=user_account.address,
            receiver=user_account,
            txType=TransactionType.REG_BONUS,
            amount=bonus_units,
            nonce=treasury_nonce,
            gasLimit=blockchain.baseTransferGas,
            gasPrice=0,
            feePaid=0,
            signature="0" * 128,
            publicKey="0" * 130,
            status=TransactionStatus.FINALIZED,
            block=new_block,
        )
        tx.full_clean()
        tx.save()

        # 10. Link BlockTransaction (ordered membership)
        btx = BlockTransaction(
            block=new_block,
            transaction=tx,
            txIndex=0,
        )
        btx.full_clean()
        btx.save()

        # 11. Create Transaction Receipt & Event
        receipt = TransactionReceipt(
            transaction=tx,
            block=new_block,
            status=ReceiptStatus.SUCCESS,
            gasUsed=0,
            effectiveGasPrice=0,
            resultCode="REGISTRATION_BONUS",
            resultMessage=f"Registration bonus of {bonus_myc} MYC allocated to {user_account.address}.",
        )
        receipt.full_clean()
        receipt.save()

        event = TransactionEvent(
            transaction=tx,
            eventType=EventType.TRANSFER,
            eventIndex=0,
            eventData={
                "allocationType": "REGISTRATION_BONUS",
                "amount": bonus_units,
                "recipientAddress": user_account.address,
                "senderAddress": treasury_account.address,
            },
        )
        event.full_clean()
        event.save()

        # 12. Finalize Block and update Blockchain finalized tip
        new_block.status = BlockStatus.FINALIZED
        new_block.finalizedAt = timezone.now()
        new_block.full_clean()
        new_block.save()

        blockchain.latestFinalizedBlock = new_block
        blockchain.full_clean()
        blockchain.save(update_fields=["latestFinalizedBlock", "updatedAt"])

        logger.info(
            "Registration bonus granted: 100 MYC -> %s (Tx: %s, Block: #%d)",
            user_account.address,
            tx_hash[:12],
            new_height,
        )

        return RegistrationBonusResult(
            account=user_account,
            transaction=tx,
            block=new_block,
            bonus_units=bonus_units,
            bonus_myc=bonus_myc,
        )

