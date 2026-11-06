"""
Phase 5 verification tests: Mempool model, priority ordering, auto-queuing,
eviction, and Mempool API routes.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.mempool_service import MempoolService
from app.services.node_service import NodeService
from app.services.transaction_service import TransactionService
from tests.test_phase4_transactions import (
    create_signed_tx_payload,
    generate_test_wallet,
)


@pytest.mark.asyncio
async def test_mempool_automatic_enqueue(test_session: AsyncSession):
    """Verify newly registered transactions automatically enter local Mempool."""
    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver_addr = "0x" + "a" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver_addr,
        amount="1000000000",
        gas_limit=21000,
        gas_price="3",
    )

    tx = await TransactionService.validate_and_register_transaction(test_session, payload)
    assert tx.status == "MEMPOOL"

    entry = await MempoolService.get_entry_by_hash(test_session, tx.txHash)
    assert entry is not None
    assert entry.txHash == tx.txHash
    assert entry.fee == str(21000 * 3)
    assert entry.priority == 3
    assert entry.status == "PENDING"


@pytest.mark.asyncio
async def test_mempool_priority_ordering(test_session: AsyncSession):
    """Verify transactions are strictly ordered by fee/gasPrice priority descending."""
    sk1, pub_hex1, sender1 = generate_test_wallet()
    sk2, pub_hex2, sender2 = generate_test_wallet()
    receiver = "0x" + "e" * 40

    # Low priority transaction (gasPrice 2)
    payload_low = create_signed_tx_payload(
        sk=sk1,
        pub_hex=pub_hex1,
        sender_addr=sender1,
        receiver_addr=receiver,
        gas_price="2",
    )
    # High priority transaction (gasPrice 10)
    payload_high = create_signed_tx_payload(
        sk=sk2,
        pub_hex=pub_hex2,
        sender_addr=sender2,
        receiver_addr=receiver,
        gas_price="10",
    )

    tx_low = await TransactionService.validate_and_register_transaction(test_session, payload_low)
    tx_high = await TransactionService.validate_and_register_transaction(test_session, payload_high)

    entries = await MempoolService.get_mempool_entries(test_session)
    assert len(entries) >= 2
    # First entry in queue MUST be the higher priority one
    assert entries[0].txHash == tx_high.txHash
    assert entries[0].priority == 10
    assert entries[1].txHash == tx_low.txHash
    assert entries[1].priority == 2


@pytest.mark.asyncio
async def test_mempool_eviction(test_session: AsyncSession):
    """Verify transactions can be evicted from the mempool."""
    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver = "0x" + "f" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver,
    )
    tx = await TransactionService.validate_and_register_transaction(test_session, payload)

    count_before = await MempoolService.get_mempool_count(test_session)
    assert count_before >= 1

    evicted = await MempoolService.remove_from_mempool(test_session, tx.txHash)
    assert evicted is True

    count_after = await MempoolService.get_mempool_count(test_session)
    assert count_after == count_before - 1


@pytest.mark.asyncio
async def test_mempool_api_endpoints(test_client: AsyncClient, test_session: AsyncSession):
    """Verify /api/v1/mempool routes and node health mempool size metric."""
    await NodeService.init_or_update_local_node(test_session)

    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver = "0x" + "d" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver,
        gas_limit=21000,
        gas_price="4",
    )

    # Submit transaction
    post_res = await test_client.post("/api/v1/transactions", json=payload.model_dump())
    assert post_res.status_code == 201
    tx_hash = post_res.json()["txHash"]

    # 1. Health check reflects mempoolSize = 1
    health_res = await test_client.get("/api/v1/node/health")
    assert health_res.status_code == 200
    assert health_res.json()["mempoolSize"] == 1

    # 2. Get mempool overview
    mempool_res = await test_client.get("/api/v1/mempool")
    assert mempool_res.status_code == 200
    mempool_data = mempool_res.json()
    assert mempool_data["totalCount"] == 1
    assert mempool_data["totalFees"] == str(21000 * 4)

    # 3. Query single mempool entry
    entry_res = await test_client.get(f"/api/v1/mempool/{tx_hash}")
    assert entry_res.status_code == 200
    assert entry_res.json()["txHash"] == tx_hash

    # 4. Evict transaction
    delete_res = await test_client.delete(f"/api/v1/mempool/{tx_hash}")
    assert delete_res.status_code == 200

    # 5. Health check reflects mempoolSize = 0
    health_res2 = await test_client.get("/api/v1/node/health")
    assert health_res2.status_code == 200
    assert health_res2.json()["mempoolSize"] == 0

