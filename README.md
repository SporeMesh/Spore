# Spore Mesh

> Decentralized AI research protocol. BitTorrent-like transport for signed, replayable experiments.

Spore turns short-lived ML experiments into a peer-to-peer network. Nodes publish signed `train.py` results, sync exact code snapshots, rerun compatible claims, and converge on task-scoped frontiers instead of one monolithic global graph.

## What Changed

The network is now organized around `task_id`.

- each task has its own root, DAG, frontier, recent activity, and verification flow
- legacy roots are backfilled automatically into separate tasks
- sync-only, verifier-only, and research nodes can all carry multiple tasks
- the explorer is task-aware by default
- signed control events are durable and replay after reconnect
- signed task manifests sync over the same gossip mesh
- global reputation is no longer the main product surface

## Quick Start

```bash
pip install sporemesh
spore set groq <your-api-key>
spore run
```

That will:

1. initialize `~/.spore`
2. connect to `peer.sporemesh.com:7470` if no peer is configured
3. sync experiments, control events, and task manifests
4. auto-select the most active known task unless you pin one
5. start the explorer on `http://localhost:8470`
6. run research if an LLM is configured

## Node Modes

- `spore run`
  Research node. Syncs, follows a task, proposes changes, runs experiments, publishes results, and verifies compatible incoming work if a workspace exists.
- `spore run --verify-only`
  Verifier-only node. Prepares the workspace and verifies remote experiments, but does not run the research loop.
- `spore run --no-train`
  Sync-only relay. Good for `peer.sporemesh.com`, explorer hosting, graph replication, and artifact serving.

Recommended topology:

- one public sync-only relay on a CPU box
- at least one research node per important hardware class
- at least one verifier-only node for fragile or busy GPUs

## Tasks

Spore no longer assumes the whole network is one objective.

Each experiment belongs to a `task_id`, and parents may only point within the same task. A task can represent:

- NanoGPT `train.py` optimization
- FFmpeg optimization
- a kernel or FFT micro-benchmark
- any other objective with a stable evaluator

### Legacy Backfill

Existing historical roots are automatically backfilled as separate legacy tasks:

- one root lineage = one task
- no record CIDs are rewritten
- old accidental extra roots stop contaminating the main frontier

### New Tasks

Create a signed task manifest locally:

```bash
spore task create \
  --name "nanogpt-train" \
  --description "Optimize train.py for lowest val_bpb in 5 minutes" \
  --task-type ml_train \
  --artifact-type python_train_script \
  --metric val_bpb \
  --goal minimize \
  --time-budget 300
```

Inspect tasks:

```bash
spore task list
spore task show <task_id>
spore task use <task_id>
```

Run against a specific task:

```bash
spore run --task <task_id>
```

If `--task` is omitted, research and verifier nodes auto-follow the most active known task.

## Verification and Disputes

Verification is task-scoped and same-class.

- crash records are skipped
- compatible non-crash records may be spot-checked
- successful reruns emit signed verification events
- mismatches open signed challenges
- challenge responses and dispute outcomes are signed and durable
- control events replay on reconnect, so nodes do not need to be online continuously

Important constraints:

- the publisher is not an independent verifier
- incompatible hardware classes do not directly compare `val_bpb`
- a lone hardware class can publish, but cannot self-verify

## Node Profiles

Profiles are signed side-channel metadata for explorer UX.

Fields:

- `display_name`
- `bio`
- `website`
- `avatar_url`
- `donation_address`

They do not affect identity, verification, or consensus.

Example:

```bash
spore profile set \
  --display-name "Sybil" \
  --bio "Independent verifier" \
  --website "https://example.com"
```

## Explorer

The explorer is now task-first.

- top-level task index
- task-scoped graph
- task-scoped frontier
- task-scoped node and activity views
- experiment detail pages that show task membership

Default URL:

```text
http://localhost:8470
```

## Auto-Operator

Spore now includes a built-in auto-operator.

Current behavior:

- periodically checks the official release manifest
- can auto-install a newer package version
- supports a constrained post-install instruction set
- restarts the running `spore run` process after an applied update

Defaults:

- enabled by default
- update interval: 6 hours
- official manifest URL stored in `config.toml`

Override per run:

```bash
spore run --no-auto-update
spore start --no-auto-update
```

## Commands

| Command | Description |
|---|---|
| `spore init` | Initialize identity and config |
| `spore run` | Run a foreground research node |
| `spore run --verify-only` | Run a verifier-only node |
| `spore run --no-train` | Run a sync-only node |
| `spore run --task <task_id>` | Pin the runtime to one task |
| `spore start` | Start the background daemon |
| `spore explorer` | Launch the explorer UI |
| `spore task list` | List known tasks |
| `spore task create ...` | Create a signed task manifest |
| `spore task show <task_id>` | Show one task |
| `spore task use <task_id>` | Save the active task in config |
| `spore status --task <task_id>` | Inspect one task locally |
| `spore frontier --task <task_id>` | Show one task frontier |
| `spore tasks` | Quick local task table |

## Launch Notes

For a public launch, the recommended setup is:

- `peer.sporemesh.com` on a sync-only relay
- `explorer.sporemesh.com` on the explorer HTTP service
- research nodes pointed at `peer.sporemesh.com:7470`
- `RTX_3060`-class nodes run with `SPORE_DISABLE_COMPILE=1` and usually `--resource 50`

## Development

From source:

```bash
git clone https://github.com/SporeMesh/Spore.git
cd Spore
pip install -e '.[dev]'
pytest -q
```

Main docs:

- [index.md](index.md)
- [program.md](program.md)
- [spec/protocol.md](spec/protocol.md)
