from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from chain.models import (
    EventType,
    MempoolStatus,
    ReceiptStatus,
    Transaction,
    TransactionEvent,
    TransactionReceipt,
    TransactionStatus,
)
from chain.tests.base import DBConstraintMixin
from chain.tests.factories import (
    make_account,
    make_blockchain,
    make_genesis,
    make_mempool_entry,
    make_node,
    make_transaction,
    uniq_hex,
)

S = TransactionStatus


class TransactionConstraintTests(DBConstraintMixin, TestCase):
    def setUp(self):
        self.chain = make_blockchain()
        self.genesis = make_genesis(self.chain)
        self.sender = make_account(self.chain, balance=1_000_000)

    def test_valid_pending_transaction(self):
        make_transaction(self.sender).full_clean()

    def test_zero_amount_rejected(self):
        self.assertDBRejects(make_transaction, self.sender, amount=0)

    def test_negative_amount_rejected(self):
        self.assertDBRejects(make_transaction, self.sender, amount=-5)

    def test_zero_gas_limit_rejected(self):
        self.assertDBRejects(make_transaction, self.sender, gas_limit=0)

    def test_negative_nonce_rejected(self):
        self.assertDBRejects(make_transaction, self.sender, nonce=-1)

    def test_hash_must_be_unique(self):
        tx = make_transaction(self.sender)
        self.assertDBRejects(make_transaction, self.sender, hash=tx.hash)

    def test_hash_format_is_validated(self):
        tx = make_transaction(self.sender)
        tx.hash = "NOT-A-HASH"
        with self.assertRaises(ValidationError) as ctx:
            tx.full_clean()
        self.assertIn("hash", ctx.exception.message_dict)

    # --- nonce conflicts / double spending ---------------------------------------------------
    def test_two_live_transactions_cannot_share_sender_and_nonce(self):
        make_transaction(self.sender, nonce=3)
        self.assertDBRejects(make_transaction, self.sender, nonce=3)

    def test_same_nonce_allowed_for_different_senders(self):
        make_transaction(self.sender, nonce=3)
        make_transaction(make_account(self.chain), nonce=3)

    def test_nonce_is_free_again_after_drop_or_reject(self):
        make_transaction(self.sender, nonce=3, status=S.DROPPED)
        make_transaction(self.sender, nonce=3, status=S.REJECTED)
        make_transaction(self.sender, nonce=3, status=S.PENDING)

    def test_finalized_transaction_blocks_nonce_reuse(self):
        make_transaction(self.sender, nonce=3, status=S.FINALIZED, block=self.genesis, fee_paid=21_000)
        self.assertDBRejects(make_transaction, self.sender, nonce=3)

    # --- lifecycle / block reference ---------------------------------------------------------
    def test_pending_transaction_cannot_have_a_block(self):
        self.assertDBRejects(make_transaction, self.sender, status=S.PENDING, block=self.genesis)

    def test_included_transaction_must_have_a_block(self):
        self.assertDBRejects(make_transaction, self.sender, status=S.INCLUDED)

    def test_finalized_transaction_must_have_a_block(self):
        self.assertDBRejects(make_transaction, self.sender, status=S.FINALIZED)

    def test_failed_transaction_in_block_pays_fee(self):
        make_transaction(self.sender, status=S.FAILED, block=self.genesis, fee_paid=21_000)

    # --- signatures --------------------------------------------------------------------------
    def test_created_transaction_may_be_unsigned(self):
        make_transaction(self.sender, status=S.CREATED, signature="", public_key="")

    def test_pending_transaction_requires_signature(self):
        self.assertDBRejects(make_transaction, self.sender, status=S.PENDING, signature="", public_key="")

    def test_signature_requires_public_key(self):
        self.assertDBRejects(make_transaction, self.sender, public_key="")

    # --- fees --------------------------------------------------------------------------------
    def test_fee_only_set_after_execution(self):
        self.assertDBRejects(make_transaction, self.sender, status=S.PENDING, fee_paid=1)

    def test_fee_cannot_exceed_gas_limit_times_price(self):
        self.assertDBRejects(
            make_transaction, self.sender, status=S.FINALIZED, block=self.genesis,
            gas_limit=21_000, gas_price=2, fee_paid=42_001,
        )

    def test_fee_at_the_limit_is_accepted(self):
        make_transaction(
            self.sender, status=S.FINALIZED, block=self.genesis,
            gas_limit=21_000, gas_price=2, fee_paid=42_000,
        )


class TransactionCleanTests(TestCase):
    def test_sender_must_belong_to_same_blockchain(self):
        tx = make_transaction(make_account(make_blockchain()))
        tx.blockchain = make_blockchain()
        with self.assertRaises(ValidationError) as ctx:
            tx.clean()
        self.assertIn("sender", ctx.exception.message_dict)

    def test_receiver_account_must_match_receiver_address(self):
        chain = make_blockchain()
        tx = make_transaction(make_account(chain))
        tx.receiver = make_account(chain)  # address differs from tx.receiver_address
        with self.assertRaises(ValidationError) as ctx:
            tx.clean()
        self.assertIn("receiver", ctx.exception.message_dict)


class ReceiptAndEventTests(DBConstraintMixin, TestCase):
    def setUp(self):
        chain = make_blockchain()
        self.genesis = make_genesis(chain)
        sender = make_account(chain, balance=1_000_000)
        self.tx = make_transaction(
            sender, status=S.FINALIZED, block=self.genesis, fee_paid=21_000, gas_limit=21_000, gas_price=1
        )

    def _receipt(self, **kw):
        data = dict(
            transaction=self.tx, block=self.genesis, status=ReceiptStatus.SUCCESS,
            gas_used=21_000, effective_gas_price=1,
        )
        data.update(kw)
        return TransactionReceipt(**data)

    def test_valid_receipt(self):
        receipt = self._receipt()
        receipt.full_clean()
        receipt.save()

    def test_one_receipt_per_transaction(self):
        self._receipt().save()
        self.assertDBRejects(self._receipt().save)

    def test_negative_gas_used_rejected(self):
        self.assertDBRejects(self._receipt(gas_used=-1).save)

    def test_gas_used_cannot_exceed_gas_limit(self):
        with self.assertRaises(ValidationError) as ctx:
            self._receipt(gas_used=21_001).clean()
        self.assertIn("gas_used", ctx.exception.message_dict)

    def test_receipt_block_must_match_transaction_block(self):
        other_block = make_genesis(make_blockchain())
        with self.assertRaises(ValidationError) as ctx:
            self._receipt(block=other_block).clean()
        self.assertIn("block", ctx.exception.message_dict)

    def test_event_index_unique_per_transaction(self):
        TransactionEvent.objects.create(transaction=self.tx, event_type=EventType.TRANSFER, event_index=0)
        self.assertDBRejects(
            TransactionEvent.objects.create,
            transaction=self.tx, event_type=EventType.FEE_PAID, event_index=0,
        )

    def test_events_are_ordered_by_index(self):
        TransactionEvent.objects.create(transaction=self.tx, event_type=EventType.FEE_PAID, event_index=1)
        TransactionEvent.objects.create(
            transaction=self.tx, event_type=EventType.TRANSFER, event_index=0, event_data={"amount": 5}
        )
        events = list(self.tx.events.order_by("event_index"))
        self.assertEqual([e.event_type for e in events], [EventType.TRANSFER, EventType.FEE_PAID])


class MempoolTests(DBConstraintMixin, TestCase):
    def setUp(self):
        self.chain = make_blockchain()
        self.node = make_node(self.chain)
        self.tx = make_transaction(make_account(self.chain, balance=1_000_000))

    def test_entry_defaults_to_active(self):
        entry = make_mempool_entry(self.tx, self.node)
        self.assertEqual(entry.status, MempoolStatus.ACTIVE)

    def test_same_transaction_once_per_node(self):
        make_mempool_entry(self.tx, self.node)
        self.assertDBRejects(make_mempool_entry, self.tx, self.node)

    def test_same_transaction_may_live_in_several_node_mempools(self):
        make_mempool_entry(self.tx, self.node)
        make_mempool_entry(self.tx, make_node(self.chain))

    def test_expiry_must_be_after_arrival(self):
        now = timezone.now()
        self.assertDBRejects(
            make_mempool_entry, self.tx, self.node, arrival_time=now, expires_at=now - timedelta(seconds=1)
        )

    def test_node_and_transaction_must_share_blockchain(self):
        entry = make_mempool_entry(self.tx, self.node)
        entry.node = make_node(make_blockchain())
        with self.assertRaises(ValidationError):
            entry.clean()
