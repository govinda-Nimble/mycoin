from django.core.exceptions import ValidationError
from django.test import TestCase

from chain.models import Account, AccountType, Wallet, WalletType
from chain.tests.base import DBConstraintMixin
from chain.tests.factories import make_account, make_blockchain, make_wallet, uniq_hex


class WalletTests(DBConstraintMixin, TestCase):
    def test_external_wallet_needs_no_key_reference(self):
        make_wallet(wallet_type=WalletType.EXTERNAL, key_reference="").full_clean()

    def test_keystore_wallet_requires_key_reference(self):
        self.assertDBRejects(make_wallet, wallet_type=WalletType.KEYSTORE, key_reference="")

    def test_keystore_wallet_with_key_reference_ok(self):
        make_wallet(wallet_type=WalletType.KEYSTORE, key_reference="vault://keys/1")

    def test_address_must_be_unique(self):
        wallet = make_wallet()
        self.assertDBRejects(make_wallet, address=wallet.address)

    def test_address_format_is_validated(self):
        wallet = Wallet(address="0xABC", public_key=uniq_hex(66))
        with self.assertRaises(ValidationError) as ctx:
            wallet.full_clean()
        self.assertIn("address", ctx.exception.message_dict)


class AccountTests(DBConstraintMixin, TestCase):
    def test_new_account_is_valid_and_starts_empty(self):
        account = make_account()
        account.full_clean()
        self.assertEqual((account.balance, account.nonce), (0, 0))

    def test_negative_balance_rejected(self):
        self.assertDBRejects(make_account, balance=-1)

    def test_negative_nonce_rejected(self):
        self.assertDBRejects(make_account, nonce=-1)

    def test_balance_is_stored_as_exact_integer(self):
        account = make_account(balance=9_000_000_000_000_000_001)
        account.refresh_from_db()
        self.assertEqual(account.balance, 9_000_000_000_000_000_001)

    def test_address_unique_per_blockchain(self):
        account = make_account()
        self.assertDBRejects(make_account, blockchain=account.blockchain, address=account.address)

    def test_same_address_allowed_on_other_blockchain(self):
        account = make_account()
        make_account(make_blockchain(), address=account.address)

    def test_one_account_per_wallet_per_blockchain(self):
        wallet = make_wallet()
        chain = make_blockchain()
        make_account(chain, wallet=wallet, address=wallet.address)
        self.assertDBRejects(make_account, chain, wallet=wallet, address="0x" + uniq_hex(40))

    def test_wallet_can_have_one_account_on_each_blockchain(self):
        wallet = make_wallet()
        make_account(make_blockchain(), wallet=wallet, address=wallet.address)
        make_account(make_blockchain(), wallet=wallet, address=wallet.address)

    def test_hd_derivation_allows_many_accounts_on_same_chain(self):
        wallet, chain = make_wallet(), make_blockchain()
        make_account(chain, wallet=wallet, derivation_index=0)
        make_account(chain, wallet=wallet, derivation_index=1)

    def test_duplicate_derivation_index_rejected(self):
        wallet, chain = make_wallet(), make_blockchain()
        make_account(chain, wallet=wallet, derivation_index=0)
        self.assertDBRejects(make_account, chain, wallet=wallet, derivation_index=0)

    def test_contract_account_cannot_have_wallet(self):
        self.assertDBRejects(make_account, account_type=AccountType.CONTRACT, wallet=make_wallet())

    def test_contract_account_without_wallet_ok(self):
        make_account(account_type=AccountType.CONTRACT)

    def test_derivation_index_requires_wallet(self):
        self.assertDBRejects(make_account, derivation_index=0)

    def test_address_must_match_wallet_when_not_derived(self):
        wallet = make_wallet()
        account = Account(blockchain=make_blockchain(), wallet=wallet, address="0x" + uniq_hex(40))
        with self.assertRaises(ValidationError) as ctx:
            account.clean()
        self.assertIn("address", ctx.exception.message_dict)
