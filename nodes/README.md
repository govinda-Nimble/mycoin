# MYC Blockchain Node Network Simulation

A decentralized P2P blockchain node network simulation consisting of three independent nodes running simultaneously on a single computer, each with its own isolated database, local mempool, peer discovery, cryptographic verification, and gossip propagation engine.

---

## 1. Architecture & Topology

```
+-------------------------------------------------------------------------------------------------+
|                                     MYC BLOCKCHAIN NETWORK                                      |
+-------------------------------------------------------------------------------------------------+

       [ Node 1 ]                          [ Node 2 ]                          [ Node 3 ]
  Identity: myc-node-001              Identity: myc-node-002              Identity: myc-node-003
  Port: 8001                          Port: 8002                          Port: 8003
  Database: myc_node_1                Database: myc_node_2                Database: myc_node_3
  Mempool: Isolated                   Mempool: Isolated                   Mempool: Isolated
       |                                   |                                   |
       +------------ P2P Gossip -----------+------------ P2P Gossip -----------+
       |                                                                       |
       +----------------------------- P2P Gossip ------------------------------+
```

### Key Decentralization Principles
1. **Identical Codebase:** All nodes execute the exact same FastAPI application codebase.
2. **Database Isolation:** Nodes **never share a database**. Each node connects to its own independent database (`myc_node_1`, `myc_node_2`, `myc_node_3`), maintaining its own private view of the network.
3. **Independent Mempools:** Each node maintains its own local mempool, queueing and prioritizing transactions by gas price and arrival time.
4. **P2P Gossip Network:** Nodes discover each other via cryptographic handshakes, broadcast transactions asynchronously, and prevent circular gossip loops using duplicate hash detection.
5. **Cryptographic Compatibility:** Uses ECDSA secp256k1 deterministic signing and SHA-256 canonical serialization identical to the MYC Django wallet backend.

---

## 2. Technology Stack

- **Framework:** FastAPI (Python 3.12+)
- **ORM / Database:** SQLAlchemy 2.0 (Async) + PostgreSQL 16 (or async SQLite for local/test mode)
- **Validation:** Pydantic v2
- **P2P Communication:** HTTPX (Asynchronous HTTP client)
- **Cryptography:** `ecdsa` (secp256k1 curve), `hashlib` (SHA-256)
- **ASGI Server:** Uvicorn
- **Containerization:** Docker & Docker Compose
- **Testing:** Pytest & pytest-asyncio

---

## 3. Quickstart Guide

### Option A: Run with Docker Compose (Recommended)

To launch all three nodes and PostgreSQL with the three isolated databases pre-provisioned:

```bash
cd nodes
docker compose up --build
```

This starts:
- **PostgreSQL 16** on `localhost:5432` with databases `myc_node_1`, `myc_node_2`, and `myc_node_3`.
- **Node 1** on `http://localhost:8001` (Docs: `http://localhost:8001/docs`)
- **Node 2** on `http://localhost:8002` (Docs: `http://localhost:8002/docs`)
- **Node 3** on `http://localhost:8003` (Docs: `http://localhost:8003/docs`)

---

### Option B: Run Locally with Uvicorn (Three Independent Terminals)

Install dependencies:
```bash
cd nodes
pip install -r requirements.txt
```

**Terminal 1 (Node 1):**
```bash
set NODE_ID=myc-node-001
set PORT=8001
set ENDPOINT=http://localhost:8001
set DATABASE_URL=sqlite+aiosqlite:///./myc_node_1.db
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

**Terminal 2 (Node 2):**
```bash
set NODE_ID=myc-node-002
set PORT=8002
set ENDPOINT=http://localhost:8002
set DATABASE_URL=sqlite+aiosqlite:///./myc_node_2.db
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

**Terminal 3 (Node 3):**
```bash
set NODE_ID=myc-node-003
set PORT=8003
set ENDPOINT=http://localhost:8003
set DATABASE_URL=sqlite+aiosqlite:///./myc_node_3.db
uvicorn app.main:app --host 0.0.0.0 --port 8003 --reload
```

---

## 4. P2P Network Peering & Discovery

### Connect Node 1 to Node 2
Send a POST request to Node 1 asking it to peer with Node 2:

```bash
curl -X POST "http://localhost:8001/api/v1/peers/connect" \
     -H "Content-Type: application/json" \
     -d '{"peerEndpoint": "http://localhost:8002"}'
```

**What happens automatically:**
1. Node 1 queries Node 2's `/api/v1/node/info`.
2. Node 1 verifies that `chainId` matches and prevents self-peering.
3. Node 1 records Node 2 in its local database as `CONNECTED`.
4. Node 1 automatically sends an inbound handshake to Node 2 (`/api/v1/peers/handshake`).
5. Node 2 records Node 1 in its own database as `CONNECTED` (establishing bidirectional P2P connectivity).

### Connect Node 2 to Node 3
```bash
curl -X POST "http://localhost:8002/api/v1/peers/connect" \
     -H "Content-Type: application/json" \
     -d '{"peerEndpoint": "http://localhost:8003"}'
```

### Inspect Known Peers
```bash
curl "http://localhost:8001/api/v1/peers"
```

---

## 5. Transaction Ingestion & Gossip Propagation

### Step 1: Submit a Signed Transaction to Node 1

Clients obtain signed transactions directly from the Django backend's `/api/wallets/sign-transaction/` endpoint, and submit the camelCase payload to Node 1:

```bash
curl -X POST "http://localhost:8001/api/v1/transactions" \
     -H "Content-Type: application/json" \
     -d '{
       "senderAddress": "0x51c70e300995bb66cf7da7a1ee9e1cce2cf51543",
       "receiverAddress": "0x9876543210abcdef9876543210abcdef98765432",
       "amount": "10000000000",
       "nonce": 0,
       "gasLimit": 21000,
       "gasPrice": "2",
       "publicKey": "04a1b2c3d4e5f67a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d",
       "signature": "0x4c2a11b..."
     }'
```

### Step 2: Verification and Local Mempool Insertion
Node 1 performs:
1. **Address Derivation Check:** Validates that `senderAddress == SHA-256(publicKey)[-40:]`.
2. **Cryptographic Signature Verification:** Verifies the ECDSA secp256k1 signature against `chainId:sender:receiver:amount:nonce:gasLimit:gasPrice`.
3. **Transaction Hashing:** Computes deterministic SHA-256 transaction hash.
4. **Mempool Enqueue:** Queues the transaction into its local mempool, sorted by gas price.

### Step 3: Gossip Broadcast to Connected Peers
Node 1 immediately forwards the transaction asynchronously to Node 2 via `POST http://localhost:8002/api/v1/transactions/receive`.
Node 2 validates, enqueues in its own mempool, and forwards to Node 3.
When Node 3 attempts to forward back to Node 1, Node 1 detects the duplicate hash and responds with `ALREADY_KNOWN`, successfully breaking circular network loops.

### Step 4: Verify Transaction across All Three Mempools
```bash
# Node 1 Mempool
curl "http://localhost:8001/api/v1/mempool"

# Node 2 Mempool
curl "http://localhost:8002/api/v1/mempool"

# Node 3 Mempool
curl "http://localhost:8003/api/v1/mempool"
```

All three nodes will report the transaction queued in their independent mempools!

---

## 6. Background Heartbeat & Failure Detection

Each node runs a background heartbeat service every 5 seconds:
- Automatically refreshes the local node's activity timestamp in the database.
- Probes all connected peers via `GET /api/v1/node/health`.
- If a peer becomes unresponsive or times out, it is immediately marked as `DISCONNECTED` and `OFFLINE`.
- If the peer restarts and responds to health checks, it is automatically marked back as `CONNECTED` and `ONLINE`.

---

## 7. API Reference Table

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Basic node status, ID, endpoint, chainId |
| `GET` | `/api/v1/health` | Fast uptime check |
| `GET` | `/api/v1/node/info` | Comprehensive node identity, public key, status |
| `GET` | `/api/v1/node/health` | Detailed diagnostics (DB status, peer count, mempool size) |
| `POST` | `/api/v1/node/heartbeat` | Trigger heartbeat refresh |
| `POST` | `/api/v1/peers/connect` | Outbound P2P connect to peer endpoint |
| `POST` | `/api/v1/peers/handshake` | Inbound handshake received from remote peer |
| `GET` | `/api/v1/peers` | List all peers in local node's database |
| `DELETE` | `/api/v1/peers/{nodeId}` | Disconnect peer |
| `POST` | `/api/v1/peers/{nodeId}/ping` | Ping peer and measure round-trip latency (ms) |
| `POST` | `/api/v1/transactions` | Ingest and broadcast new signed transaction |
| `POST` | `/api/v1/transactions/receive` | Internal P2P gossip endpoint for receiving forwarded txs |
| `GET` | `/api/v1/transactions/{txHash}` | Query transaction by hash |
| `GET` | `/api/v1/transactions/{txHash}/status`| Lightweight transaction status query |
| `GET` | `/api/v1/mempool` | View mempool queue ordered by gas price priority |
| `GET` | `/api/v1/mempool/{txHash}` | Query single mempool entry |
| `DELETE` | `/api/v1/mempool/{txHash}` | Evict transaction from mempool |

---

## 8. Test Suite Verification

Run the comprehensive unit, integration, and multi-node simulation test suite:

```bash
cd nodes
pytest -v
```

### Test Coverage Across Phases:
- `tests/test_phase1_setup.py`: Configuration defaults, root, and health check routes.
- `tests/test_phase2_node.py`: Node model persistence, idempotent self-registration, heartbeat.
- `tests/test_phase3_peers.py`: NodePeer model, bidirectional handshake, self-peering prevention, peer listing.
- `tests/test_phase4_transactions.py`: ECDSA secp256k1 verification, address derivation, tampered amount rejection, duplicate prevention.
- `tests/test_phase5_mempool.py`: Automatic queuing, gas-price priority ordering, mempool metrics, eviction.
- `tests/test_phase6_propagation.py`: P2P gossip ingestion, network key verification, loop prevention.
- `tests/test_phase7_heartbeat.py`: Periodic heartbeat monitor, dead peer failure detection, offline transitions.
- `tests/test_phase8_network_simulation.py`: End-to-end 3-node simulation (Alice -> Node 1 -> Node 2 -> Node 3 -> Node 1 echo loop prevention).

