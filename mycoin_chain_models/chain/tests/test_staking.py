from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from chain.models import (
    AccountType,
    BlockVote,
    SlashingRecord,
    Stake,
    StakeStatus,
    ValidatorReward,
    ValidatorStatus,
    VoteType,
    OffenceType,
    RewardType,
)
from chain.tests.base import DBConstraintMixin
from chain.tests.factories import (
    make_account,
    make_blockchain,
    make_genesis,
    make_next_block,
    make_validator,
    uniq_hex,
)


class ValidatorTests(DBConstraintMixin, TestCase):
    def setUp(self):
        self.chain = make_blockchain()

    def test_valid_validator(self):
        make_validator(self.chain).full_clean()

    def test_one_validator_per_account(self):
        validator = make_validator(self.chain)
        self.assertDBRejects(make_validator, self.chain, account=validator.account)

    def test_public_key_unique(self):
        validator = make_validator(self.chain)
        self.assertDBRejects(make_validator, self.chain, public_key=validator.public_key)

    def test_negative_total_stake_rejected(self):
        self.assertDBRejects(make_validator, self.chain, total_stake=-1)

    def test_commission_must_be_within_0_and_100(self):
        self.assertDBRejects(make_validator, self.chain, commission_percent=Decimal("100.01"))
        self.assertDBRejects(make_validator, self.chain, commission_percent=Decimal("-0.01"))
        make_validator(self.chain, commission_percent=100)

    def test_active_validator_needs_activation_time(self):
        self.assertDBRejects(make_validator, self.chain, status=ValidatorStatus.ACTIVE, activated_at=None)

    def test_pending_validator_needs_no_activation_time(self):
        make_validator(self.chain, status=ValidatorStatus.PENDING, activated_at=None)

    def test_contract_account_cannot_be_validator(self):
        validator = make_validator(self.chain, account=make_account(self.chain, account_type=AccountType.CONTRACT))
        with self.assertRaises(ValidationError):
            validator.clean()


class StakeTests(DBConstraintMixin, TestCase):
    def setUp(self):
        self.chain = make_blockchain()
        self.validator = make_validator(self.chain)
        self.staker = make_account(self.chain, balance=10**10)

    def _stake(self, **kw):
        data = dict(validator=self.validator, staker_account=self.staker, amount=10**9, staked_at_height=1)
        data.update(kw)
        return Stake.objects.create(**data)

    def test_valid_active_stake(self):
        self._stake().full_clean()

    def test_zero_amount_rejected(self):
        self.assertDBRejects(self._stake, amount=0)

    def test_unbonding_stake_requires_unlock_height_and_request_time(self):
        self.assertDBRejects(self._stake, status=StakeStatus.UNBONDING)
        self._stake(status=StakeStatus.UNBONDING, unlock_height=100, unstake_requested_at=timezone.now())

    def test_unlock_height_cannot_precede_stake_height(self):
        self.assertDBRejects(self._stake, staked_at_height=50, unlock_height=49)

    def test_one_account_can_stake_repeatedly(self):
        self._stake()
        self._stake(amount=5)

    def test_staker_must_be_on_same_blockchain_as_validator(self):
        stake = self._stake()
        stake.staker_account = make_account(make_blockchain())
        with self.assertRaises(ValidationError):
            stake.clean()


class VotingTests(DBConstraintMixin, TestCase):
    def setUp(self):
        self.chain = make_blockchain()
        self.validator = make_validator(self.chain)
        self.block = make_next_block(make_genesis(self.chain), self.validator)

    def _vote(self, **kw):
        data = dict(
            block=self.block, validator=self.validator, vote_type=VoteType.APPROVE,
            voting_power=10, signature=uniq_hex(128),
        )
        data.update(kw)
        return BlockVote.objects.create(**data)

    def test_valid_vote(self):
        self._vote().full_clean()

    def test_validator_votes_once_per_block(self):
        self._vote()
        self.assertDBRejects(self._vote, vote_type=VoteType.REJECT)

    def test_validators_can_vote_on_several_blocks(self):
        self._vote()
        self._vote(block=make_next_block(self.block.parent, self.validator))

    def test_voting_power_must_be_positive(self):
        self.assertDBRejects(self._vote, voting_power=0)

    def test_validator_must_be_on_same_blockchain_as_block(self):
        vote = self._vote()
        vote.validator = make_validator(make_blockchain())
        with self.assertRaises(ValidationError):
            vote.clean()


class RewardAndSlashingTests(DBConstraintMixin, TestCase):
    def setUp(self):
        chain = make_blockchain()
        self.validator = make_validator(chain)
        self.block = make_next_block(make_genesis(chain), self.validator)

    def _reward(self, **kw):
        data = dict(validator=self.validator, block=self.block, amount=500, reward_type=RewardType.BLOCK_REWARD)
        data.update(kw)
        return ValidatorReward.objects.create(**data)

    def test_one_reward_per_validator_block_and_type(self):
        self._reward()
        self.assertDBRejects(self._reward)

    def test_block_reward_and_fee_reward_can_coexist(self):
        self._reward()
        self._reward(reward_type=RewardType.TX_FEES, amount=21)

    def test_reward_must_be_positive(self):
        self.assertDBRejects(self._reward, amount=0)

    def _slash(self, **kw):
        data = dict(
            validator=self.validator, offence_type=OffenceType.DOUBLE_SIGN,
            slashed_amount=100, evidence_hash="a" * 64,
        )
        data.update(kw)
        return SlashingRecord.objects.create(**data)

    def test_same_evidence_cannot_be_slashed_twice(self):
        self._slash()
        self.assertDBRejects(self._slash)

    def test_different_evidence_is_a_new_offence(self):
        self._slash()
        self._slash(evidence_hash="b" * 64)

    def test_slashed_amount_must_be_positive(self):
        self.assertDBRejects(self._slash, slashed_amount=0)

    def test_evidence_hash_format_validated(self):
        record = self._slash()
        record.evidence_hash = "xyz"
        with self.assertRaises(ValidationError):
            record.full_clean()
