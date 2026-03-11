# Spore Protocol Specification

> Current task-aware protocol and runtime semantics.

## 1. Overview

Spore is a peer-to-peer protocol for collaborative AI research.

The network exchanges four durable signed objects:

- experiment records
- task manifests
- control events
- node profiles

Artifacts are content-addressed blobs fetched separately by CID.

## 2. Identity

Each node has an Ed25519 keypair.

- private key: local only
- public key: `node_id`

The `node_id` is the signer identity for:

- experiment publishing
- task creation
- profile metadata
- verification and challenges
- dispute outcomes

## 3. Task Manifest

Implementation: `spore/task.py`

The task manifest defines an objective namespace above experiments.

### Fields

| Field | Meaning |
|---|---|
| `task_id` | SHA-256 of canonical manifest bytes |
| `name` | human-readable task label |
| `description` | task description |
| `task_type` | task family such as `ml_train` |
| `artifact_type` | artifact class such as `python_train_script` |
| `metric` | metric being optimized |
| `goal` | `minimize` or `maximize` |
| `base_code_cid` | optional baseline artifact CID |
| `prepare_cid` | optional evaluator/prep artifact CID |
| `dataset_cid` | optional dataset identifier |
| `time_budget` | intended per-run time budget |
| `created_by` | signer node id |
| `timestamp` | unix timestamp |
| `signature` | Ed25519 signature |
| `version` | manifest version |

### Legacy Tasks

Historical roots that predate task support are backfilled locally:

- `task_id = root_experiment_cid`
- no experiment CID is rewritten
- legacy tasks are durable metadata, not new signed manifests

## 4. Experiment Record

Implementation: `spore/record.py`

Experiments are immutable signed records.

### Important Fields

| Field | Meaning |
|---|---|
| `id` | SHA-256 CID of canonical record bytes |
| `task_id` | task namespace for this experiment |
| `parent` | parent experiment CID or null |
| `code_cid` | exact code artifact CID |
| `val_bpb` | current primary metric for ML tasks |
| `status` | `keep`, `discard`, or `crash` |
| `node_id` | publisher |
| `signature` | Ed25519 signature |
| `version` | record version |

### Canonical Rules

- `id` and `signature` are excluded from canonical bytes
- `task_id` is part of the canonical payload for v2+ records
- CID and signature must both verify

### Lineage Rules

- parent and child must share the same `task_id`
- normal experiments inside a task must have a parent
- only the task root is parentless
- second roots in an existing task are rejected

## 5. Control Events

Implementation: `spore/control.py`, `spore/control_store.py`

Control events are signed records for:

- `challenge`
- `challenge_response`
- `verification`
- `dispute`

They are:

- signed by the acting node
- stored durably in SQLite
- replayed on reconnect via control sync

These are not ephemeral gossip hints anymore. They are replayable facts.

## 6. Profiles

Implementation: `spore/profile.py`

Profiles are signed metadata for explorer UX only.

Fields include:

- `display_name`
- `bio`
- `website`
- `avatar_url`
- `donation_address`

Profiles are not consensus-critical.

## 7. Graph Model

Implementation: `spore/graph.py`

The local graph is:

- append-only
- task-aware
- SQLite-backed

Important queries:

- `frontier_by_task(task_id)`
- `best_by_task(task_id)`
- `recent_by_task(task_id)`
- legacy `frontier()` / `recent()` across all tasks

## 8. Wire Protocol

Implementation: `spore/wire.py`, `spore/gossip.py`

Messages are length-prefixed JSON over TCP.

### Message Types

| Type | Payload |
|---|---|
| `experiment` | signed experiment record |
| `task` | signed task manifest |
| `sync_request` | experiment sync request |
| `sync_response` | experiment sync completion marker |
| `control_sync_request` | control-event sync request |
| `control_sync_response` | control sync completion marker |
| `task_sync_request` | task-manifest sync request |
| `task_sync_response` | task sync completion marker |
| `pex_request` | peer exchange request |
| `pex_response` | canonical peer list |
| `challenge` | signed control event |
| `challenge_response` | signed control event |
| `verification` | signed control event |
| `dispute` | signed control event |
| `profile` | signed node profile |
| `code_request` | artifact request by `code_cid` |
| `code_response` | artifact bytes |

### Sync Semantics

At startup, a node requests:

1. experiment sync
2. control-event sync
3. task sync

The startup path waits for completion responses instead of assuming that a successful TCP connect implies a completed sync.

## 9. Verification Semantics

Implementation: `spore/verify.py`, `spore/challenge.py`

Verification is:

- task-scoped
- same-class
- tolerance-based

Rules:

- crash records are skipped
- incompatible hardware classes do not authoritatively compare metrics
- successful reruns emit `verification`
- mismatches emit `challenge`
- challenge volunteers emit `challenge_response`
- challenger resolves to a `dispute`

## 10. Artifact Semantics

Implementation: `spore/store.py`, `spore/artifact_sync.py`

Artifacts are addressed by `code_cid`.

Rules:

- bytes are verified against CID after transfer
- nodes may prefetch artifacts on experiment receipt
- multiple fetches for the same artifact should share one inflight request

## 11. Auto-Operator

Implementation: `spore/operator.py`

This is a runtime feature, not a consensus object.

Current operator behavior:

- fetch official release manifest over HTTPS
- compare versions
- install a newer package when available
- run only constrained post-install instructions
- restart the local `spore run` process

Supported instructions currently include:

- `copy_workspace`
- `backfill_tasks`

## 12. Explorer Semantics

The explorer is task-first:

- `/api/tasks`
- `/api/task/{task_id}`
- task-scoped graph, frontier, recent, node, and search endpoints

Global reputation is intentionally not the main protocol abstraction anymore. The explorer emphasizes tasks, frontier, and verification state instead.
