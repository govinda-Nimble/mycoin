"""Small helpers that build valid model instances for tests (override anything via kwargs)."""
import hashlib
import itertools
from datetime import timedelta

from django.utils import timezone

from chain.models import (
    GENESIS_PREVIOUS_HASH,
    Account,
    Block,
    BlockStatus,
    Blockchain,
    MempoolTransaction,
    Node,
    Transaction,
    TransactionStatus,
    Validator,
    ValidatorStatus,
    Wallet,
    WalletType,
)

_seq = itertools.count(1)
_nonce = itertools.count(0)


def uniq_hex(length=64):
    return hashlib.sha256(str(next(_seq)).encode()).hexdigest()[:length]


def make_blockchain(**kw):
    n = next(_seq)
    data = {"chain_id": 1000 + n, "name": f"mycoin-test-{n}"}
    data.update(kw)
    return Blockchain.objects.create(**data)


def make_wallet(**kw):
    data = {
        "address": "0x" + uniq_hex(40),
        "public_key": uniq_hex(66),
        "wallet_type": WalletType.EXTERNAL,
    }
    data.update(kw)
    return Wallet.objects.create(**data)


def make_account(blockchain=None, **kw):
    data = {"blockchain": blockchain or make_blockchain(), "address": "0x" + uniq_hex(40)}
    data.update(kw)
    return Account.objects.create(**data)


def make_node(blockchain=None, **kw):
    n = next(_seq)
    data = {
        "blockchain": blockchain or make_blockchain(),
        "node_id": f"node-{n}",
        "endpoint": f"127.0.0.1:{9000 + n}",
    }
    data.update(kw)
    return Node.objects.create(**data)


def make_validator(blockchain=None, **kw):
    account = kw.pop("account", None) or make_account(blockchain)
    data = {
        "account": account,
        "public_key": uniq_hex(66),
        "status": ValidatorStatus.ACTIVE,
        "activated_at": timezone.now(),
    }
    data.update(kw)
    return Validator.objects.create(**data)


def make_genesis(blockchain, **kw):
    now = timezone.now()
    data = {
        "blockchain": blockchain,
        "height": 0,
        "block_hash": uniq_hex(),
        "previous_hash": GENESIS_PREVIOUS_HASH,
        "merkle_root": uniq_hex(),
        "timestamp": now,
        "status": BlockStatus.FINALIZED,
        "finalized_at": now,
    }
    data.update(kw)
    return Block.objects.create(**data)


def make_next_block(parent, proposer, **kw):
    data = {
        "blockchain": parent.blockchain,
        "height": parent.height + 1,
        "parent": parent,
        "previous_hash": parent.block_hash,
        "block_hash": uniq_hex(),
        "merkle_root": uniq_hex(),
        "timestamp": timezone.now(),
        "proposer": proposer,
        "status": BlockStatus.PROPOSED,
    }
    data.update(kw)
    return Block.objects.create(**data)


def make_transaction(sender, **kw):
    data = {
        "hash": uniq_hex(),
        "blockchain": sender.blockchain,
        "sender": sender,
        "receiver_address": "0x" + uniq_hex(40),
        "amount": 100,
        "nonce": next(_nonce),
        "gas_limit": 21_000,
        "gas_price": 1,
        "signature": uniq_hex(128),
        "public_key": uniq_hex(66),
        "status": TransactionStatus.PENDING,
    }
    data.update(kw)
    return Transaction.objects.create(**data)


def make_mempool_entry(transaction, node, **kw):
    now = timezone.now()
    data = {
        "transaction": transaction,
        "node": node,
        "arrival_time": now,
        "expires_at": now + timedelta(hours=1),
    }
    data.update(kw)
    return MempoolTransaction.objects.create(**data)
