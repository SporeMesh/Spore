# Spore Protocol Specification

> Version 0.1 — March 2026

---

## 1. Overview

Spore is a peer-to-peer protocol for collaborative AI research. Nodes run autonomous ML experiments, publish results as immutable records, and collectively build a directed acyclic graph (DAG) of research findings.

Unlike distributed training systems (Petals, Hivemind, Prime Intellect), Spore distributes **research** — independent experiments that build on each other. The atomic unit is a 5-minute experiment, not a gradient update.

## 2. Experiment Record

The protocol's atom. See `spore/record.py` for implementation.

### 2.1 Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | CID: SHA-256 of canonical payload |
| `version` | int | Protocol version (1) |
| `parent` | string? | Parent experiment CID |
| `depth` | int | Distance from genesis |
| `code_cid` | string | SHA-256 of train.py snapshot |
| `diff` | string | Unified diff from parent |
| `dataset_cid` | string | Hash of dataset |
| `prepare_cid` | string | Hash of evaluation harness |
| `time_budget` | int | Training time in seconds |
| `val_bpb` | float | Validation bits per byte |
| `peak_vram_mb` | float | Peak GPU memory |
| `num_steps` | int | Training steps completed |
| `num_params` | int | Model parameter count |
| `status` | enum | keep / discard / crash |
| `description` | string | What was tried |
| `hypothesis` | string | Agent's reasoning |
| `agent_model` | string | LLM that proposed this |
| `gpu_model` | string | GPU identifier |
| `cuda_version` | string | CUDA/driver version |
| `torch_version` | string | PyTorch version |
| `node_id` | string | Ed25519 public key (hex) |
| `timestamp` | int | Unix timestamp |
| `signature` | string | Ed25519 signature (hex) |

### 2.2 CID Computation

1. Serialize all fields except `id` and `signature` as canonical JSON (sorted keys, no whitespace, ASCII-only)
2. SHA-256 hash the JSON bytes
3. Hex-encode the hash → this is the CID

### 2.3 Signing

1. Compute canonical JSON bytes (same as CID input)
2. Sign with node's Ed25519 private key
3. Store hex-encoded signature in `signature` field

### 2.4 Verification

A record is valid if:
- `id` matches recomputed CID
- `signature` verifies against `node_id` public key
- `parent` exists in the graph (or is null for genesis)
- `status` is one of: keep, discard, crash
- `val_bpb > 0` (or 0 for crashes)

## 3. Research Graph

### 3.1 Structure

A Merkle-DAG where each experiment points to its parent via the `parent` field. The graph is:

- **Append-only**: Records are never deleted or modified
- **Content-addressed**: Each record's CID depends on its content
- **Convergent**: Two nodes exchanging records converge without coordination (grow-only CRDT)

### 3.2 Frontier

The frontier is the set of unbeaten experiments — experiments whose status is `keep` and no child has a lower `val_bpb`. Computed locally:

```sql
SELECT e.* FROM experiment e
WHERE e.status = 'keep'
AND NOT EXISTS (
    SELECT 1 FROM experiment c
    WHERE c.parent = e.id
    AND c.status = 'keep'
    AND c.val_bpb < e.val_bpb
)
ORDER BY e.val_bpb ASC
```

### 3.3 GPU-Class Frontier

Different GPU classes process different token counts in the fixed time budget, making val_bpb incomparable across classes. Each GPU class has its own frontier.

## 4. Wire Protocol

### 4.1 Message Format

Length-prefixed JSON over TCP:
```
[4 bytes: big-endian uint32 length][UTF-8 JSON body]
```

### 4.2 Message Types

| Type | Payload | Direction |
|------|---------|-----------|
| `experiment` | Full ExperimentRecord | Broadcast |
| `sync_request` | `{since: timestamp}` | Request |
| `sync_response` | `[ExperimentRecord, ...]` | Response |
| `pex_request` | `{}` | Request |
| `pex_response` | `{peer: ["host:port", ...]}` | Response |
| `challenge` | `{experiment_id, challenger_id, challenger_bpb, challenger_gpu}` | Broadcast |
| `challenge_response` | `{experiment_id, challenger_id, verifier_id, verifier_bpb, verifier_gpu}` | Broadcast |
| `dispute` | `{experiment_id, challenger_id, challenger_bpb, outcome, ground_truth_bpb, verifier_count}` | Broadcast |
| `ping` | `{}` | Request |
| `pong` | `{}` | Response |

### 4.3 Gossip

When a node produces or receives a new experiment:
1. Validate record (CID, signature)
2. Check CID against local seen-set (dedup)
3. Insert into local graph
4. Re-broadcast to all connected peers except source

### 4.4 Sync

When a node joins or reconnects:
1. Send `sync_request` with `since` = timestamp of latest local experiment
2. Peer responds with all experiments after that timestamp
3. Node validates and inserts each record

### 4.5 Peer Exchange (PEX)

After connecting to a peer, a node requests its peer list:
1. Send `pex_request`
2. Peer responds with `pex_response` containing all its connected peer addresses (excluding the requester)
3. Node auto-connects to discovered peers and persists them to `~/.spore/known_peer`

This allows the network to grow organically — connecting to one peer discovers the rest.

### 4.6 Peer Discovery

Nodes discover the network via:
1. **Bootstrap peer**: ` 188.36.196.221:42208` (used when no peers are configured and not in genesis mode)
2. **Persisted known peer**: `~/.spore/known_peer` (peers from previous sessions)
3. **PEX**: peer lists received from connected peers
4. **Manual config**: `spore connect <host:port>` or `--peer` flag

Genesis mode (`--genesis`) skips all peer connection — use this when starting the first node in a new network.

NAT'd nodes (e.g., laptops behind a router) can connect outbound to public peers and participate fully. They receive all gossip through their outbound connections. Port forwarding is only needed to accept inbound connections from other peers.

## 5. Autonomous Experiment Loop

Each research node runs a continuous loop:

1. **Select parent**: Pick an experiment from the frontier (best unbeaten results)
2. **Propose**: Send the current `train.py` + parent context to a configured LLM. The LLM proposes a modification (architecture, hyperparameters, optimizer, etc.)
3. **Run**: Apply the proposed code change and execute training (5-minute budget)
4. **Evaluate**: Parse val_bpb from output. If lower than parent → keep, otherwise discard
5. **Publish**: Create a signed ExperimentRecord with the result and gossip it to peers
6. **Repeat**: Return to step 1

### 5.1 LLM Provider

Nodes configure an LLM provider via `spore set <provider> <api_key>`. Supported providers:
- Groq (`openai/gpt-oss-120b`)
- Anthropic (`claude-sonnet-4-5-20250929`)
- OpenAI (`gpt-4o`)
- xAI (`grok-3`)
- Custom OpenAI-compatible endpoint

All providers use the OpenAI chat completions format.

### 5.2 Resource Control

Nodes can limit resource usage with `--resource N` (1-100, default 100). This scales the training batch size proportionally, reducing GPU memory and CPU usage.

## 6. Verification

### 6.1 Tolerance Band

Same code on same GPU class produces val_bpb within a tolerance band due to floating-point non-determinism. Empirically calibrated per GPU class.

Expected: ±0.002 val_bpb within same GPU family.

### 6.2 Spot-Checking

Nodes probabilistically spot-check incoming experiments:
- Base rate: 5% of all experiments
- 3x rate for nodes with negative reputation
- 2x rate for nodes with reputation < 5
- 2x rate for suspiciously low val_bpb (< 0.9)

When spot-checking, the node retrieves the full code snapshot from the artifact store, re-runs training, and compares the result against the claimed val_bpb.

### 6.3 Challenge Protocol

1. Spot-checker re-runs the experiment on compatible hardware (same GPU class)
2. If result exceeds tolerance band, broadcasts `CHALLENGE` message
3. Up to 3 verifiers with matching GPU class volunteer and re-run
4. Verifiers broadcast `CHALLENGE_RESPONSE` with their val_bpb
5. Challenger collects responses (10-minute timeout)
6. Median of all results (original + challenger + verifiers) = ground truth
7. If original exceeds tolerance from ground truth → `REJECTED`, original loses reputation
8. Otherwise → `UPHELD`, challenger loses reputation
9. Challenger broadcasts final `DISPUTE` with outcome

### 6.4 Sybil Defense

- Hardware attestation (throughput must match claimed GPU)
- Statistical anomaly detection
- Reputation-gated frontier influence

## 7. Reputation

### 7.1 Score

Float in [-100, +100], starting at 0.

| Event | Delta |
|-------|-------|
| Verified keep | +1.0 |
| Verified discard | +0.3 |
| Frontier advance | +2.0 |
| Verification performed | +0.5 |
| Dispute won | +1.0 |
| Dispute lost | -5.0 |

### 7.2 Effect

- Graph sync priority
- Verification weight
- Rate limiting for low-reputation nodes

## 8. Default Port

`7470` (S-P-O-R on a phone keypad, close enough)

## 9. Future Extension

- libp2p transport (GossipSub, Kademlia DHT)
- IPFS artifact storage
- Multi-metric Pareto frontiers
- Research directives (multiple program.md channels)
- Cross-GPU-class insight transfer
- Federation between Spore networks
