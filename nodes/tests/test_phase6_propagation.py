"""
Phase 6 verification tests: P2P transaction propagation, loop prevention,
gossip receipt endpoint, and network security authentication.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.propagation import PropagatedTransactionPayload
from app.services.mempool_service import MempoolService
from app.services.node_service import NodeService
from app.services.propagation_service import PropagationService
from app.services.transaction_service import TransactionService
from tests.test_phase4_transactions import (
    create_signed_tx_payload,
    generate_test_wallet,
)


@pytest.mark.asyncio
async def test_receive_propagated_transaction_success(
    test_client: AsyncClient,
    test_session: AsyncSession,
):
    """Verify incoming gossiped transaction is ingested and queued in mempool."""
    await NodeService.init_or_update_local_node(test_session)

    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver_addr = "0x" + "8" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver_addr,
        amount="888000000",
    )

    prop_payload = PropagatedTransactionPayload(
        **payload.model_dump(),
        originNodeId="myc-node-002",
        hopCount=1,
    )

    res = await test_client.post(
        "/api/v1/transactions/receive",
        json=prop_payload.model_dump(),
        headers={"X-Network-Key": settings.NETWORK_KEY},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ACCEPTED"
    tx_hash = data["txHash"]

    # Verify transaction entered local mempool
    mempool_entry = await MempoolService.get_entry_by_hash(test_session, tx_hash)
    assert mempool_entry is not None
    assert mempool_entry.txHash == tx_hash


@pytest.mark.asyncio
async def test_receive_duplicate_prevents_loop(
    test_client: AsyncClient,
    test_session: AsyncSession,
):
    """Verify loop prevention: duplicate gossiped transactions are flagged ALREADY_KNOWN."""
    await NodeService.init_or_update_local_node(test_session)

    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver_addr = "0x" + "7" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver_addr,
        amount="777000000",
    )

    prop_payload = PropagatedTransactionPayload(
        **payload.model_dump(),
        originNodeId="myc-node-002",
        hopCount=1,
    )

    # First receive: ACCEPTED
    res1 = await test_client.post(
        "/api/v1/transactions/receive",
        json=prop_payload.model_dump(),
        headers={"X-Network-Key": settings.NETWORK_KEY},
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "ACCEPTED"

    # Second receive: ALREADY_KNOWN
    res2 = await test_client.post(
        "/api/v1/transactions/receive",
        json=prop_payload.model_dump(),
        headers={"X-Network-Key": settings.NETWORK_KEY},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "ALREADY_KNOWN"


@pytest.mark.asyncio
async def test_receive_unauthorized_network_key(test_client: AsyncClient):
    """Verify gossip endpoint requires valid X-Network-Key header."""
    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver_addr = "0x" + "6" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver_addr,
    )

    res = await test_client.post(
        "/api/v1/transactions/receive",
        json=payload.model_dump(),
        headers={"X-Network-Key": "wrong-secret-key"},
    )
    assert res.status_code == 401
    assert "Invalid or missing X-Network-Key" in res.json()["detail"]


@pytest.mark.asyncio
async def test_broadcast_with_no_peers(test_session: AsyncSession):
    """Verify broadcast handles nodes without peers gracefully."""
    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver_addr = "0x" + "5" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver_addr,
    )

    result = await PropagationService.broadcast_transaction(payload)
    assert result.peersContacted == 0
    assert result.peersAccepted == 0

