from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from chain.models import (
    GENESIS_PREVIOUS_HASH,
    Block,
    BlockStatus,
    BlockTransaction,
    ImmutableRecordError,
    TransactionStatus,
)
from chain.tests.base import DBConstraintMixin
from chain.tests.factories import (
    make_account,
    make_blockchain,
    make_genesis,
    make_next_block,
    make_transaction,
    make_validator,
    uniq_hex,
)


class BlockConstraintTests(DBConstraintMixin, TestCase):
    def setUp(self):
        self.chain = make_blockchain()
        self.genesis = make_genesis(self.chain)
        self.validator = make_validator(self.chain)

    def test_valid_chain_of_blocks(self):
        block = make_next_block(self.genesis, self.validator)
        block.full_clean()
        self.assertEqual(block.parent, self.genesis)

    def test_genesis_must_not_have_proposer(self):
        self.assertDBRejects(make_genesis, make_blockchain(), proposer=self.validator)

    def test_non_genesis_requires_parent(self):
        self.assertDBRejects(
            Block.objects.create,
            blockchain=self.chain,
            height=1,
            block_hash=uniq_hex(),
            previous_hash=self.genesis.block_hash,
            merkle_root=uniq_hex(),
            timestamp=timezone.now(),
            proposer=self.validator,
        )

    def test_non_genesis_requires_proposer(self):
        self.assertDBRejects(make_next_block, self.genesis, None)

    def test_block_hash_unique_per_blockchain(self):
        self.assertDBRejects(make_next_block, self.genesis, self.validator, block_hash=self.genesis.block_hash)

    def test_two_proposals_may_share_a_height(self):
        make_next_block(self.genesis, self.validator)
        make_next_block(self.genesis, self.validator)

    def test_only_one_finalized_block_per_height(self):
        first = make_next_block(self.genesis, self.validator)
        second = make_next_block(self.genesis, self.validator)
        first.status, first.finalized_at = BlockStatus.FINALIZED, timezone.now()
        first.save()
        second.status, second.finalized_at = BlockStatus.FINALIZED, timezone.now()
        self.assertDBRejects(second.save)

    def test_finalized_block_needs_finalized_at(self):
        self.assertDBRejects(make_next_block, self.genesis, self.validator, status=BlockStatus.FINALIZED)

    def test_negative_gas_used_rejected(self):
        self.assertDBRejects(make_next_block, self.genesis, self.validator, gas_used=-1)


class BlockCleanTests(TestCase):
    def setUp(self):
        self.chain = make_blockchain()
        self.genesis = make_genesis(self.chain)
        self.validator = make_validator(self.chain)

    def _field_errors(self, block):
        with self.assertRaises(ValidationError) as ctx:
            block.clean()
        return ctx.exception.message_dict

    def test_previous_hash_must_match_parent(self):
        block = make_next_block(self.genesis, self.validator)
        block.previous_hash = uniq_hex()
        self.assertIn("previous_hash", self._field_errors(block))

    def test_height_must_follow_parent(self):
        block = make_next_block(self.genesis, self.validator)
        block.height = 5
        self.assertIn("height", self._field_errors(block))

    def test_genesis_previous_hash_must_be_zeros(self):
        genesis = make_genesis(make_blockchain(), previous_hash=uniq_hex())
        self.assertIn("previous_hash", self._field_errors(genesis))

    def test_genesis_with_zero_previous_hash_is_clean(self):
        self.assertEqual(self.genesis.previous_hash, GENESIS_PREVIOUS_HASH)
        self.genesis.clean()

    def test_parent_must_be_on_same_blockchain(self):
        other_genesis = make_genesis(make_blockchain())
        block = make_next_block(self.genesis, self.validator)
        block.parent, block.previous_hash, block.height = other_genesis, other_genesis.block_hash, 1
        self.assertIn("parent", self._field_errors(block))


class BlockImmutabilityTests(TestCase):
    def setUp(self):
        self.chain = make_blockchain()
        self.genesis = make_genesis(self.chain)
        self.validator = make_validator(self.chain)

    def test_finalized_block_cannot_be_modified(self):
        self.genesis.gas_used = 5
        with self.assertRaises(ImmutableRecordError):
            self.genesis.save()

    def test_finalized_block_cannot_be_deleted(self):
        with self.assertRaises(ImmutableRecordError):
            self.genesis.delete()
        self.assertTrue(Block.objects.filter(pk=self.genesis.pk).exists())

    def test_proposed_block_can_be_finalized_once_then_is_frozen(self):
        block = make_next_block(self.genesis, self.validator)
        block.status, block.finalized_at = BlockStatus.FINALIZED, timezone.now()
        block.save()  # PROPOSED -> FINALIZED is allowed
        block.merkle_root = uniq_hex()
        with self.assertRaises(ImmutableRecordError):
            block.save()

    def test_proposed_block_can_be_rejected_and_deleted(self):
        block = make_next_block(self.genesis, self.validator)
        block.status = BlockStatus.REJECTED
        block.save()
        block.delete()


class BlockTransactionTests(DBConstraintMixin, TestCase):
    def setUp(self):
        self.chain = make_blockchain()
        self.genesis = make_genesis(self.chain)
        self.validator = make_validator(self.chain)
        self.block = make_next_block(self.genesis, self.validator)
        self.sender = make_account(self.chain, balance=1_000_000)

    def _tx(self):
        return make_transaction(self.sender, status=TransactionStatus.INCLUDED, block=self.block)

    def test_transactions_are_ordered_by_unique_index(self):
        BlockTransaction.objects.create(block=self.block, transaction=self._tx(), tx_index=0)
        self.assertDBRejects(
            BlockTransaction.objects.create, block=self.block, transaction=self._tx(), tx_index=0
        )

    def test_transaction_cannot_be_in_two_blocks(self):
        other = make_next_block(self.genesis, self.validator)
        tx = self._tx()
        BlockTransaction.objects.create(block=self.block, transaction=tx, tx_index=0)
        self.assertDBRejects(BlockTransaction.objects.create, block=other, transaction=tx, tx_index=0)

    def test_rows_of_rejected_proposal_can_be_removed_and_tx_reproposed(self):
        tx = self._tx()
        entry = BlockTransaction.objects.create(block=self.block, transaction=tx, tx_index=0)
        entry.delete()
        tx.status, tx.block = TransactionStatus.PENDING, None
        tx.save()
        other = make_next_block(self.genesis, self.validator)
        BlockTransaction.objects.create(block=other, transaction=tx, tx_index=0)

    def test_finalized_block_transactions_are_frozen(self):
        tx = make_transaction(self.sender, status=TransactionStatus.FINALIZED, block=self.genesis)
        with self.assertRaises(ImmutableRecordError):
            BlockTransaction.objects.create(block=self.genesis, transaction=tx, tx_index=0)

    def test_block_and_transaction_must_share_blockchain(self):
        foreign_tx = make_transaction(make_account(make_blockchain()))
        entry = BlockTransaction(block=self.block, transaction=foreign_tx, tx_index=0)
        with self.assertRaises(ValidationError):
            entry.clean()
