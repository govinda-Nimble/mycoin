"""
Phase 4 verification tests: Cryptographic signature verification, address derivation,
transaction hashing, duplicate prevention, and transaction API routes.
"""

import hashlib
import ecdsa
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.transaction import SignedTransactionPayload
from app.services.transaction_service import TransactionService


def generate_test_wallet():
    """Generates a test ECDSA secp256k1 keypair and derives the MYC wallet address."""
    sk = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1)
    vk = sk.get_verifying_key()
    pub_hex = ("04" + vk.to_string().hex()).lower()
    address_hash = hashlib.sha256(vk.to_string()).hexdigest().lower()
    address = "0x" + address_hash[-40:]
    return sk, pub_hex, address


def create_signed_tx_payload(
    sk: ecdsa.SigningKey,
    pub_hex: str,
    sender_addr: str,
    receiver_addr: str,
    amount: str = "1000000000",
    nonce: int = 0,
    gas_limit: int = 21000,
    gas_price: str = "2",
    chain_id: int = 1001,
) -> SignedTransactionPayload:
    """Signs a canonical payload and constructs a SignedTransactionPayload."""
    canonical_payload = (
        f"{chain_id}:"
        f"{sender_addr.lower()}:"
        f"{receiver_addr.lower()}:"
        f"{amount}:"
        f"{nonce}:"
        f"{gas_limit}:"
        f"{gas_price}"
    )
    digest = hashlib.sha256(canonical_payload.encode("utf-8")).digest()
    raw_sig = sk.sign_deterministic(
        digest,
        hashfunc=hashlib.sha256,
        sigencode=ecdsa.util.sigencode_string,
    )
    sig_hex = "0x" + raw_sig.hex().lower()

    return SignedTransactionPayload(
        senderAddress=sender_addr,
        receiverAddress=receiver_addr,
        amount=amount,
        nonce=nonce,
        gasLimit=gas_limit,
        gasPrice=gas_price,
        publicKey=pub_hex,
        signature=sig_hex,
    )


@pytest.mark.asyncio
async def test_cryptographic_verification_success():
    """Verify that a validly signed payload passes cryptographic verification."""
    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver_addr = "0x" + "b" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver_addr,
        amount="5000000000",
    )

    is_valid, reason = TransactionService.verify_cryptographic_signature(
        payload,
        settings.CHAIN_ID,
    )
    assert is_valid is True
    assert reason == ""


@pytest.mark.asyncio
async def test_cryptographic_verification_tampered_amount():
    """Verify that tampering with the amount causes signature verification to fail."""
    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver_addr = "0x" + "b" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver_addr,
        amount="1000",
    )

    # Tamper with amount after signing
    payload.amount = "999999"

    is_valid, reason = TransactionService.verify_cryptographic_signature(
        payload,
        settings.CHAIN_ID,
    )
    assert is_valid is False
    assert "Invalid cryptographic signature" in reason


@pytest.mark.asyncio
async def test_cryptographic_verification_mismatched_address():
    """Verify that providing a publicKey that does not derive senderAddress is rejected."""
    sk, pub_hex, _ = generate_test_wallet()
    fake_sender = "0x" + "f" * 40
    receiver_addr = "0x" + "b" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=fake_sender,
        receiver_addr=receiver_addr,
    )

    is_valid, reason = TransactionService.verify_cryptographic_signature(
        payload,
        settings.CHAIN_ID,
    )
    assert is_valid is False
    assert "does not match public key" in reason


@pytest.mark.asyncio
async def test_transaction_service_ingestion_and_duplicate_prevention(test_session: AsyncSession):
    """Verify TransactionService records transaction and rejects duplicate hashes."""
    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver_addr = "0x" + "b" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver_addr,
        amount="2500000000",
    )

    # Ingest
    tx = await TransactionService.validate_and_register_transaction(test_session, payload)
    assert tx.id is not None
    assert tx.txHash.startswith("0x")
    assert tx.status == "PENDING"
    assert tx.amount == "2500000000"

    # Re-ingest duplicate
    with pytest.raises(ValueError, match="Duplicate transaction"):
        await TransactionService.validate_and_register_transaction(test_session, payload)


@pytest.mark.asyncio
async def test_transaction_api_routes(test_client: AsyncClient, test_session: AsyncSession):
    """Verify POST /api/v1/transactions and GET /api/v1/transactions/{tx_hash}."""
    sk, pub_hex, sender_addr = generate_test_wallet()
    receiver_addr = "0x" + "c" * 40

    payload = create_signed_tx_payload(
        sk=sk,
        pub_hex=pub_hex,
        sender_addr=sender_addr,
        receiver_addr=receiver_addr,
        amount="100000000",
    )

    # 1. Submit transaction
    post_res = await test_client.post("/api/v1/transactions", json=payload.model_dump())
    assert post_res.status_code == 201
    post_data = post_res.json()
    assert "txHash" in post_data
    tx_hash = post_data["txHash"]
    assert post_data["status"] == "PENDING"

    # 2. Query transaction details
    get_res = await test_client.get(f"/api/v1/transactions/{tx_hash}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["txHash"] == tx_hash
    assert get_data["senderAddress"] == sender_addr.lower()

    # 3. Query transaction status
    status_res = await test_client.get(f"/api/v1/transactions/{tx_hash}/status")
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "PENDING"

