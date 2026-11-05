from django.test import TestCase

from chain.models import NodePeer, NodeType
from chain.tests.base import DBConstraintMixin
from chain.tests.factories import make_blockchain, make_node, make_validator, uniq_hex


class BlockchainTests(DBConstraintMixin, TestCase):
    def test_defaults_are_valid(self):
        make_blockchain().full_clean()

    def test_chain_id_is_unique(self):
        make_blockchain(chain_id=7)
        self.assertDBRejects(make_blockchain, chain_id=7, name="another")

    def test_finality_numerator_must_be_below_denominator(self):
        self.assertDBRejects(make_blockchain, finality_numerator=3, finality_denominator=3)

    def test_finality_numerator_must_be_positive(self):
        self.assertDBRejects(make_blockchain, finality_numerator=0)

    def test_decimals_above_18_rejected(self):
        self.assertDBRejects(make_blockchain, decimals=19)

    def test_zero_block_gas_rejected(self):
        self.assertDBRejects(make_blockchain, max_block_gas=0)


class NodeTests(DBConstraintMixin, TestCase):
    def test_endpoint_unique_per_blockchain(self):
        node = make_node(endpoint="10.0.0.1:9000")
        self.assertDBRejects(make_node, blockchain=node.blockchain, endpoint="10.0.0.1:9000")

    def test_same_endpoint_allowed_on_other_blockchain(self):
        make_node(endpoint="10.0.0.1:9000")
        make_node(endpoint="10.0.0.1:9000")  # new blockchain from the factory

    def test_validator_node_requires_validator(self):
        self.assertDBRejects(make_node, node_type=NodeType.VALIDATOR)

    def test_validator_node_with_validator_ok(self):
        chain = make_blockchain()
        make_node(chain, node_type=NodeType.VALIDATOR, validator=make_validator(chain))

    def test_node_id_unique(self):
        make_node(node_id="same")
        self.assertDBRejects(make_node, node_id="same")


class NodePeerTests(DBConstraintMixin, TestCase):
    def setUp(self):
        chain = make_blockchain()
        self.a, self.b = make_node(chain), make_node(chain)

    def test_cannot_peer_with_self(self):
        self.assertDBRejects(NodePeer.objects.create, local_node=self.a, peer_node=self.a)

    def test_duplicate_pair_rejected(self):
        NodePeer.objects.create(local_node=self.a, peer_node=self.b)
        self.assertDBRejects(NodePeer.objects.create, local_node=self.a, peer_node=self.b)

    def test_reverse_direction_is_a_separate_row(self):
        NodePeer.objects.create(local_node=self.a, peer_node=self.b)
        NodePeer.objects.create(local_node=self.b, peer_node=self.a)
