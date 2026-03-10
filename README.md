# Spore Mesh

> Decentralized AI research protocol. BitTorrent for ML experiments.

Spore turns autonomous `train.py` experimentation into a peer-to-peer network. Each node runs short ML experiments, publishes immutable signed results, verifies other nodes by rerunning claims, and collectively builds a research DAG.

Spore is based on Karpathy's [autoresearch](https://github.com/karpathy/autoresearch), but the unit of exchange is not a gradient or checkpoint shard. It is a cheap-to-rerun, content-addressed experiment.

## What Exists Today

The current repo includes:

- Signed experiment records and a local SQLite DAG
- TCP gossip with dedup, sync, peer exchange, and code artifact transfer
- Frontier-aware autonomous experiment loop
- Probabilistic spot-checking, challenges, disputes, and propagated reputation updates
- Artifact prefetch and shared code-fetch coordination
- Local training serialization plus isolated verification workspaces
- GPU normalization for verification classes across CUDA, MPS, and CPU
- Signed node profile metadata for display names and donation links
- Explorer UI with graph, frontier, activity, leaderboard, and node profile display

## Quick Start

```bash
pip install sporemesh
spore set groq <your-api-key>
spore run
```

That will:

1. initialize `~/.spore/`
2. connect to the bootstrap peer if no peer is configured
3. sync the experiment DAG
4. prepare workspace files if needed
5. fetch the best known frontier code if available
6. start the explorer on `http://localhost:8470`
7. begin running experiments if an LLM is configured

## Install

```bash
pip install sporemesh
```

From source:

```bash
git clone https://github.com/SporeMesh/Spore.git
cd Spore
pip install -e '.[dev]'
```

Optional CUDA extras:

```bash
pip install -e '.[cuda]'
```

Requirements:

- Python 3.11+
- CUDA, Apple MPS, or CPU
- outbound network access to at least one peer

## Operating Modes

Spore has three practical node modes:

- `spore run`
  Research node. Syncs, fetches frontier code, asks the LLM for changes, runs experiments, publishes results, and verifies incoming compatible experiments if a workspace exists.
- `spore run --no-train`
  Sync-only node. Useful for graph replication or explorer attachment. Does not run the experiment loop.
- `spore run --verify-only`
  Verifier-only node. Prepares the workspace and verifies remote experiments, but does not run the LLM research loop.

Recommended live topology:

- at least one research node per important hardware class
- at least one verifier-only node for busy or fragile GPUs
- at least two compatible nodes for any hardware class you expect to verify

If a hardware class has only one live node, that node can publish but cannot be independently verified by same-class peers.

## Constrained Hardware Guidance

`RTX_3060`-class cards and similar smaller GPUs need tighter runtime policy than large cards.

Current safety behavior:

- local compile policy disables `torch.compile` by default on small CUDA cards
- local training and spot-checking never overlap on one node
- verification runs in an isolated temp workspace
- generated `train.py` candidates are screened by a local proposal policy before execution

Recommended settings for fragile GPUs:

```bash
SPORE_DISABLE_COMPILE=1 spore run --resource 50
```

or, for a dedicated verifier:

```bash
SPORE_DISABLE_COMPILE=1 spore run --verify-only --resource 50
```

Notes:

- `--resource` scales `DEVICE_BATCH_SIZE` and snaps to a valid divisor in the bundled workspace code.
- The applied frontier `train.py` is still experiment content. If the frontier itself is old or unstable, package-side runtime fixes do not rewrite that historical code snapshot.

## Command Reference

| Command | Description |
|---|---|
| `spore init` | Initialize identity, config, db, and artifact directories |
| `spore set <provider> <key>` | Configure the LLM provider |
| `spore run` | Run a foreground research node |
| `spore run --resource N` | Scale resource usage to `1..100` percent |
| `spore run --no-train` | Run a sync-only node |
| `spore run --verify-only` | Run a verifier-only node |
| `spore run --genesis` | Prepare data first and skip peer connection |
| `spore explorer` | Launch explorer UI with a gossip server |
| `spore status` | Show graph status, frontier, and recent experiments |
| `spore graph` | Print the experiment DAG as ASCII |
| `spore frontier` | Show current unbeaten experiments |
| `spore info` | Show node identity and config |
| `spore connect <host:port>` | Add a configured peer |
| `spore disconnect <host:port>` | Remove a configured peer |
| `spore peer` | List configured and discovered peers |
| `spore start` | Start the background daemon |
| `spore stop` | Stop the background daemon |
| `spore log` | Show daemon logs |
| `spore clean` | Remove local Spore data |
| `spore profile show` | Show the local signed node profile |
| `spore profile set --display-name ...` | Set the local signed node profile |
| `spore version` | Show installed version |

## Node Profiles

Node identity is the Ed25519 `node_id`. Profiles are presentation metadata layered on top.

Profile fields:

- `display_name`
- `bio`
- `website`
- `avatar_url`
- `donation_address`
- `timestamp`
- `schema_version`

Profiles are:

- signed by the node's existing private key
- stored separately from graph and reputation
- gossiped independently from experiments
- used by the explorer and search surfaces only

They are intentionally not consensus-critical. Reputation, verification, and graph identity all still bind to `node_id`, not the profile.

Example:

```bash
spore profile set \
  --display-name "Sybil" \
  --bio "Independent verifier on RTX 3060" \
  --website "https://example.com" \
  --donation-address "0xabc..."
```

## Verification and Reputation

Verification is same-class rerun, not trust-by-assertion.

Current behavior:

- nodes probabilistically spot-check compatible incoming experiments
- crash records are skipped for spot-check and challenge verification
- successful spot-checks propagate as network-wide verification events
- incompatible GPU classes do not compare val_bpb directly
- challenge responses and dispute outcomes propagate across the mesh
- reputation updates are idempotent and event-based

Current reputation effects:

- verified `keep`: `+1.0`
- verified frontier `keep`: `+2.0`
- verified `discard`: `+0.3`
- verified `crash`: `+0.1`
- verification performed: `+0.5`
- dispute won: `+1.0`
- dispute lost: `-5.0`

Important protocol realities:

- the original publisher does not count as an independent verifier
- a challenge uses up to 3 independent same-class verifiers, but only as many as the graph topology actually provides
- the default challenge timeout is 30 minutes (`SPORE_CHALLENGE_TIMEOUT`)
- one isolated hardware class cannot self-verify

## Explorer

The explorer runs automatically under `spore run` when a free port is available.

Default URL:

```text
http://localhost:8470
```

Explorer features:

- graph view of experiments and lineage
- frontier table
- recent activity
- reputation leaderboard
- experiment detail, diff, code artifact, and lineage
- node profile display names and donation metadata
- live websocket updates

## Data Layout

Default data directory:

```text
~/.spore/
```

Layout:

```text
~/.spore/
├── artifact/              # Content-addressed code snapshots
├── config.toml            # Node configuration
├── db/
│   ├── graph.sqlite       # Experiment DAG
│   ├── profile.sqlite     # Signed node profiles
│   └── reputation.sqlite  # Reputation + processed event ids
├── identity/
│   ├── node_id
│   └── private_key
├── known_peer
├── llm.toml
└── log/
    └── spore.log
```

Workspace files copied into the current working directory on first run:

- `train.py`
- `prepare.py`
- `batching.py`

## Architecture

Core modules:

```text
spore/
├── agent.py            # Frontier-aware parent selection and prompt context
├── artifact_sync.py    # Shared code fetch coordination and prefetch
├── challenge.py        # Challenge protocol coordinator
├── challenge_state.py  # Verification/dispute event application helpers
├── cli.py              # CLI entry point
├── compile_policy.py   # Local compile-disable policy
├── gossip.py           # TCP gossip transport and message routing
├── gpu.py              # GPU normalization and verification classes
├── graph.py            # SQLite DAG of experiments
├── llm.py              # Provider-agnostic chat client
├── node.py             # SporeNode orchestration
├── profile.py          # Signed node profile metadata + storage
├── proposal_policy.py  # Local runtime safety checks for generated train.py
├── record.py           # ExperimentRecord + signing / CID logic
├── reputation.py       # Reputation persistence + idempotent event tracking
├── runner.py           # Training subprocess runner and parser
├── training_runtime.py # Serialized local execution + isolated verification
├── verify.py           # Spot-check policy, tolerance, dispute resolution
├── wire.py             # Wire message helpers
├── workspace/
│   ├── batching.py
│   ├── prepare.py
│   └── train.py
└── explorer/
    ├── server.py
    └── static/
```

## Current Limits

The repo is much closer to a working live network than the original prototype, but a few limits remain:

- val_bpb is only directly comparable within a normalized verification class
- historic frontier code can still contain older runtime assumptions
- profile gossip is live and opportunistic, not a historical sync stream
- low-end GPUs remain more fragile than large cards even with compile disabled
- verifier availability is bounded by actual same-class peers in the graph

## Development

Install dev dependencies:

```bash
pip install -e '.[dev]'
```

Run tests:

```bash
pytest -q
```

## Why Spore

Most decentralized ML systems distribute training. Spore distributes research.

That changes everything:

- experiments are cheap enough to verify
- results can live in an append-only DAG
- many independent nodes can explore in parallel
- the network can converge on better code without centralized coordination

See [spec/protocol.md](spec/protocol.md) for the protocol-level details.
