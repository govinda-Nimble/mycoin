from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient

from network.services.genesis import GenesisConfig, initialize_blockchain
from network.services.node_seeder import seed_validator_node
from staking.models import Validator


class StakingAPITests(TestCase):
    """API tests for the DDD layered Staking endpoints."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.genesis_config = GenesisConfig(chain_id=1001, chain_name="TEST_CHAIN")
        self.genesis_res = initialize_blockchain(self.genesis_config)
        self.blockchain = self.genesis_res.blockchain

        self.seed_res = seed_validator_node(
            node_id="val-test-001",
            endpoint="http://localhost:8001",
            stake_amount_myc=1000,
            commission_percent=Decimal("5.00"),
            node_status="ONLINE",
        )
        self.validator = self.seed_res.validator

    def test_list_validators_api(self):
        response = self.client.get("/api/staking/validators/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["publicKey"], self.validator.publicKey)

    def test_get_validator_detail_by_id(self):
        response = self.client.get(f"/api/staking/validators/{self.validator.id}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["publicKey"], self.validator.publicKey)

    def test_get_validator_detail_by_address(self):
        response = self.client.get(f"/api/staking/validators/{self.validator.account.address}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["publicKey"], self.validator.publicKey)

    def test_get_validator_not_found(self):
        response = self.client.get("/api/staking/validators/0x0000000000000000000000000000000000000000/")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["success"])
