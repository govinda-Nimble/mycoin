"""
Block production and transaction execution service.

Packages selected active Mempool transactions into a finalized Block:
1. Calculates sequential height and parent linkage.
2. Computes pairwise SHA256 Merkle root, state root, and block header hash.
3. Assembles BlockTransaction records.
4. Executes state transitions (deducts sender balance & gas fee, increments sender nonce,
   credits receiver account, credits validator fees).
5. Generates immutable TransactionReceipt and TransactionEvent records.
6. Marks transactions as FINALIZED and mempool records as INCLUDED.
7. Finalizes the Block and advances the Blockchain tip.
"""

import hashlib
import logging
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from ledger.models import (
    Block,
    BlockStatus,
    BlockTransaction,
    EventType,
    MempoolStatus,
    MempoolTransaction,
    ReceiptStatus,
    Transaction,
    TransactionEvent,
    TransactionReceipt,
    TransactionStatus,
)
from network.models import Account, AccountStatus, AccountType, Blockchain
from staking.models import Validator, ValidatorStatus

logger = logging.getLogger("ledger.block_producer")


def compute_merkle_root(tx_hashes: List[str]) -> str:
    """Computes a deterministic 64-character lowercase SHA256 Merkle root."""
    if not tx_hashes:
        return hashlib.sha256(b"empty_block").hexdigest().lower()

    # Leaf nodes are raw hash bytes
    current_level = [bytes.fromhex(h) for h in tx_hashes]
    while len(current_level) > 1:
        if len(current_level) % 2 == 1:
            current_level.append(current_level[-1])
        next_level = []
        for i in range(0, len(current_level), 2):
            combined = hashlib.sha256(current_level[i] + current_level[i + 1]).digest()
            next_level.append(combined)
        current_level = next_level

    return current_level[0].hex().lower()


def compute_state_root(parent_state_root: str, merkle_root: str, block_height: int) -> str:
    """Derives state root placeholder from parent state root and block merkle root."""
    seed = f"{parent_state_root or '0' * 64}:{merkle_root}:{block_height}"
    return hashlib.sha256(seed.encode()).hexdigest().lower()


def compute_block_hash(
    chain_id: int,
    height: int,
    previous_hash: str,
    merkle_root: str,
    state_root: str,
    timestamp_int: int,
) -> str:
    """Derives canonical SHA256 block hash from header facts."""
    material = f"{chain_id}:{height}:{previous_hash}:{merkle_root}:{state_root}:{timestamp_int}"
    return hashlib.sha256(material.encode()).hexdigest().lower()


def produce_block_from_mempool(
    blockchain: Blockchain,
    mempool_entries: List[MempoolTransaction],
) -> Optional[Block]:
    """
    Packages a batch of eligible mempool transactions into a finalized block.
    Executes balance updates, creates receipts, and marks mempool records as INCLUDED.

    Must be called inside a `transaction.atomic()` block.
    """
    if not mempool_entries:
        return None

    # 1. Resolve parent block (latest finalized block on this chain)
    blockchain.refresh_from_db()
    parent_block = (
        Block.objects.filter(blockchain=blockchain, status=BlockStatus.FINALIZED).order_by("-height").first()
        or Block.objects.filter(blockchain=blockchain).order_by("-height").first()
    )
    if not parent_block:
        logger.error("Cannot produce block: No genesis or parent block found for chain %s.", blockchain.chainId)
        return None

    # 2. Resolve proposer validator
    proposer = (
        Validator.objects.filter(account__blockchain=blockchain, status=ValidatorStatus.ACTIVE)
        .select_related("account")
        .order_by("-totalStake")
        .first()
        or Validator.objects.filter(account__blockchain=blockchain)
        .select_related("account")
        .first()
    )
    if not proposer:
        logger.error("Cannot produce block: No validator registered for chain %s.", blockchain.chainId)
        return None

    new_height = parent_block.height + 1
    now = timezone.now()
    timestamp_int = int(now.timestamp())

    # Sort candidates so that transactions from the same sender execute in ascending nonce order
    ordered_entries = sorted(
        mempool_entries,
        key=lambda m: (m.transaction.sender_id, m.transaction.nonce),
    )

    tx_hashes = [mtx.transaction.hash for mtx in ordered_entries]
    merkle_root = compute_merkle_root(tx_hashes)
    state_root = compute_state_root(parent_block.stateRoot, merkle_root, new_height)
    block_hash = compute_block_hash(
        blockchain.chainId,
        new_height,
        parent_block.blockHash,
        merkle_root,
        state_root,
        timestamp_int,
    )

    # 3. Create Block in PROPOSED status first (so BlockTransaction can be saved)
    block = Block(
        blockchain=blockchain,
        height=new_height,
        blockHash=block_hash,
        parent=parent_block,
        previousHash=parent_block.blockHash,
        merkleRoot=merkle_root,
        stateRoot=state_root,
        timestamp=now,
        proposer=proposer,
        status=BlockStatus.PROPOSED,
        transactionCount=len(ordered_entries),
        gasUsed=0,
        blockReward=0,
        epoch=0,
        round=0,
        proposerSignature="0" * 128,
    )
    block.full_clean()
    block.save()

    total_gas_used = 0

    # 4. Execute transactions and update state
    for idx, mtx in enumerate(ordered_entries):
        tx = mtx.transaction
        effective_fee = tx.gasLimit * tx.gasPrice
        total_cost = tx.amount + effective_fee

        sender = Account.objects.select_for_update().get(id=tx.sender_id)

        # Check execution conditions: adequate balance and valid sequential nonce
        if sender.balance >= total_cost and sender.nonce == tx.nonce:
            # Deduct sender balance and increment nonce
            sender.balance -= total_cost
            sender.nonce += 1
            sender.save(update_fields=["balance", "nonce", "updatedAt"])

            # Credit receiver account (create if needed)
            receiver_acc, _ = Account.objects.get_or_create(
                blockchain=blockchain,
                address=tx.receiverAddress,
                defaults={
                    "accountType": AccountType.EOA,
                    "balance": 0,
                    "nonce": 0,
                    "status": AccountStatus.ACTIVE,
                    "creationBlock": block,
                },
            )
            receiver_acc.balance += tx.amount
            receiver_acc.save(update_fields=["balance", "updatedAt"])

            # Credit proposer with transaction fees
            if effective_fee > 0 and proposer.account_id:
                proposer_acc = Account.objects.select_for_update().get(id=proposer.account_id)
                proposer_acc.balance += effective_fee
                proposer_acc.save(update_fields=["balance", "updatedAt"])

            # Update Transaction
            tx.receiver = receiver_acc
            tx.feePaid = effective_fee
            tx.block = block
            tx.status = TransactionStatus.FINALIZED
            tx.save(update_fields=["receiver", "feePaid", "block", "status", "updatedAt"])

            # Link BlockTransaction
            BlockTransaction.objects.create(
                block=block,
                transaction=tx,
                txIndex=idx,
            )

            # Create Receipt
            TransactionReceipt.objects.create(
                transaction=tx,
                block=block,
                status=ReceiptStatus.SUCCESS,
                gasUsed=tx.gasLimit,
                effectiveGasPrice=tx.gasPrice,
                resultCode="SUCCESS",
                resultMessage=f"Transferred {tx.amount} units to {tx.receiverAddress}",
            )

            # Create Events
            TransactionEvent.objects.create(
                transaction=tx,
                eventType=EventType.TRANSFER,
                eventIndex=0,
                eventData={
                    "sender": sender.address,
                    "receiver": tx.receiverAddress,
                    "amount": tx.amount,
                },
            )
            if effective_fee > 0:
                TransactionEvent.objects.create(
                    transaction=tx,
                    eventType=EventType.FEE_PAID,
                    eventIndex=1,
                    eventData={
                        "fee": effective_fee,
                        "recipient": proposer.account.address if proposer.account else "",
                    },
                )

            total_gas_used += tx.gasLimit

        else:
            # Transaction failed execution at runtime (e.g. balance dropped or nonce mismatch)
            tx.feePaid = 0
            tx.block = block
            tx.status = TransactionStatus.FAILED
            tx.save(update_fields=["feePaid", "block", "status", "updatedAt"])

            BlockTransaction.objects.create(
                block=block,
                transaction=tx,
                txIndex=idx,
            )

            reason = (
                f"Insufficient balance ({sender.balance} < {total_cost})"
                if sender.balance < total_cost
                else f"Nonce mismatch (expected {sender.nonce}, got {tx.nonce})"
            )

            # Advance sender nonce so that a transaction mined into a block as FAILED
            # consumes its nonce slot and does not permanently break or fail subsequent sequential transactions.
            sender.nonce = max(sender.nonce, tx.nonce + 1)
            sender.save(update_fields=["nonce", "updatedAt"])

            TransactionReceipt.objects.create(
                transaction=tx,
                block=block,
                status=ReceiptStatus.FAILED,
                gasUsed=0,
                effectiveGasPrice=0,
                resultCode="EXECUTION_FAILED",
                resultMessage=reason,
            )

        # Mark MempoolTransaction as INCLUDED so it leaves the active mempool
        mtx.status = MempoolStatus.INCLUDED
        mtx.save(update_fields=["status", "updatedAt"])

    # 5. Finalize Block
    block.gasUsed = total_gas_used
    block.status = BlockStatus.FINALIZED
    block.finalizedAt = timezone.now()
    block.save(update_fields=["gasUsed", "status", "finalizedAt", "updatedAt"])

    # 6. Update Blockchain tip
    blockchain.latestFinalizedBlock = block
    blockchain.save(update_fields=["latestFinalizedBlock", "updatedAt"])

    logger.info(
        "Produced and finalized Block #%d (%s) containing %d transaction(s). Gas used: %d.",
        block.height,
        block.blockHash[:12],
        len(ordered_entries),
        total_gas_used,
    )
    return block

