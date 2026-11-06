"""
Phase 8 End-to-End Network Simulation Test:
Simulates complete 3-node decentralized lifecycle:
1. Alice signs a 100 MYC transfer to Bob using ECDSA secp256k1.
2. Ingests into Node 1 -> verified, hashed, added to Node 1's Mempool.
3. Propagates from Node 1 to Node 2 -> verified, added to Node 2's Mempool.
4. Propagates from Node 2 to Node 3 -> verified, added to Node 3's Mempool.
5. Node 3 attempts echo back to Node 1 -> Node 1 detects duplicate and halts circular gossip loop.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import get_db
from app.core.config import settings
from app.database.base import Base
from app.main import create_app
from app.schemas.propagation import PropagatedTransactionPayload
from app.services.mempool_service import MempoolService
from app.services.transaction_service import TransactionService
from tests.test_phase4_transactions import (
    create_signed_tx_payload,
    generate_test_wallet,
)


@pytest.fixture
async def three_isolated_node_databases():
    """Provisions 3 independent in-memory databases simulating Node 1, Node 2, and Node 3."""
    engines = [
        create_async_engine(f"sqlite+aiosqlite:///:memory:", echo=False)
        for _ in range(3)
    ]
    sessions = []

    for eng in engines:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        sessions.append(maker)

    yield sessions

    for eng in engines:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


@pytest.mark.asyncio
async def test_end_to_end_three_node_propagation_simulation(three_isolated_node_databases):
    """
    Complete end-to-end simulation across 3 independent nodes:
    Alice -> Node 1 -> Node 2 -> Node 3 -> Node 1 loop prevention.
    """
    node1_maker, node2_maker, node3_maker = three_isolated_node_databases

    app_node1 = create_app()
    app_node2 = create_app()
    app_node3 = create_app()

    # Step 1: Alice creates an ECDSA wallet and signs a 100 MYC transfer to Bob
    alice_sk, alice_pub, alice_addr = generate_test_wallet()
    _, _, bob_addr = generate_test_wallet()

    signed_payload = create_signed_tx_payload(
        sk=alice_sk,
        pub_hex=alice_pub,
        sender_addr=alice_addr,
        receiver_addr=bob_addr,
        amount="10000000000",  # 100 MYC in 8-decimal base units
        nonce=0,
        gas_limit=21000,
        gas_price="2",
        chain_id=settings.CHAIN_ID,
    )

    # Step 2: Ingest into Node 1 via client API
    async with node1_maker() as session1:
        async def override_db1():
            yield session1

        app_node1.dependency_overrides[get_db] = override_db1
        transport1 = ASGITransport(app=app_node1)
        async with AsyncClient(transport=transport1, base_url="http://node1") as client1:
            res1 = await client1.post("/api/v1/transactions", json=signed_payload.model_dump())
            assert res1.status_code == 201
            tx_data1 = res1.json()
            tx_hash = tx_data1["txHash"]
            assert tx_data1["status"] in ("PENDING", "MEMPOOL")

            # Verify tx is in Node 1's local Mempool
            mempool1 = await MempoolService.get_entry_by_hash(session1, tx_hash)
            assert mempool1 is not None
            assert mempool1.amount == "10000000000"

    # Step 3: Node 1 propagates to Node 2 (P2P gossip)
    prop_to_node2 = PropagatedTransactionPayload(
        **signed_payload.model_dump(),
        originNodeId="myc-node-001",
        hopCount=1,
    )

    async with node2_maker() as session2:
        async def override_db2():
            yield session2

        app_node2.dependency_overrides[get_db] = override_db2
        transport2 = ASGITransport(app=app_node2)
        async with AsyncClient(transport=transport2, base_url="http://node2") as client2:
            res2 = await client2.post(
                "/api/v1/transactions/receive",
                json=prop_to_node2.model_dump(),
                headers={"X-Network-Key": settings.NETWORK_KEY},
            )
            assert res2.status_code == 200
            assert res2.json()["status"] == "ACCEPTED"

            # Verify tx is in Node 2's local Mempool
            mempool2 = await MempoolService.get_entry_by_hash(session2, tx_hash)
            assert mempool2 is not None
            assert mempool2.txHash == tx_hash

    # Step 4: Node 2 propagates to Node 3 (P2P gossip)
    prop_to_node3 = PropagatedTransactionPayload(
        **signed_payload.model_dump(),
        originNodeId="myc-node-002",
        hopCount=2,
    )

    async with node3_maker() as session3:
        async def override_db3():
            yield session3

        app_node3.dependency_overrides[get_db] = override_db3
        transport3 = ASGITransport(app=app_node3)
        async with AsyncClient(transport=transport3, base_url="http://node3") as client3:
            res3 = await client3.post(
                "/api/v1/transactions/receive",
                json=prop_to_node3.model_dump(),
                headers={"X-Network-Key": settings.NETWORK_KEY},
            )
            assert res3.status_code == 200
            assert res3.json()["status"] == "ACCEPTED"

            # Verify tx is in Node 3's local Mempool
            mempool3 = await MempoolService.get_entry_by_hash(session3, tx_hash)
            assert mempool3 is not None
            assert mempool3.txHash == tx_hash

    # Step 5: Circular Gossip Loop Prevention
    # Node 3 attempts to gossip back to Node 1 -> Node 1 detects duplicate and returns ALREADY_KNOWN
    prop_echo_to_node1 = PropagatedTransactionPayload(
        **signed_payload.model_dump(),
        originNodeId="myc-node-003",
        hopCount=3,
    )

    async with node1_maker() as session1_again:
        async def override_db1_again():
            yield session1_again

        app_node1.dependency_overrides[get_db] = override_db1_again
        transport1 = ASGITransport(app=app_node1)
        async with AsyncClient(transport=transport1, base_url="http://node1") as client1:
            echo_res = await client1.post(
                "/api/v1/transactions/receive",
                json=prop_echo_to_node1.model_dump(),
                headers={"X-Network-Key": settings.NETWORK_KEY},
            )
            assert echo_res.status_code == 200
            assert echo_res.json()["status"] == "ALREADY_KNOWN"

