# Spore

> Repository index for the current task-aware protocol.

## What Spore Is

Spore is a decentralized research mesh for signed, replayable experiments.

The core unit is an experiment record plus its exact `train.py` snapshot. Nodes gossip experiments, task manifests, control events, and artifacts over a raw TCP mesh.

## Current Architecture

- `task` is the namespace above experiments
- `experiment` is one signed step within a task
- `control event` is a signed challenge, verification, or dispute record
- `artifact` is the exact code snapshot referenced by `code_cid`
- `profile` is signed display metadata for the explorer

## Start Here

- [README.md](README.md): install, run modes, operator notes, launch setup
- [program.md](program.md): runtime doctrine and operating rules
- [spec/protocol.md](spec/protocol.md): record, task, sync, and wire semantics

## Important Files

- `spore/record.py`
  Signed experiment record and CID logic.
- `spore/task.py`
  Signed task manifest.
- `spore/graph.py`
  SQLite DAG with task-aware frontier and backfill logic.
- `spore/task_store.py`
  Durable task metadata and manifest store.
- `spore/control.py`
  Signed control-plane event type.
- `spore/control_store.py`
  Durable replay store for signed control events.
- `spore/gossip.py`
  TCP transport for experiments, tasks, control events, PEX, and artifacts.
- `spore/node.py`
  Node orchestration, sync startup, task selection, and local persistence.
- `spore/loop.py`
  Research loop.
- `spore/challenge.py`
  Verification, challenge, and dispute flow.
- `spore/operator.py`
  Auto-update operator.
- `spore/explorer/server.py`
  Explorer app wiring.
- `spore/explorer/routes.py`
  Task-aware explorer API.

## Product Surface

The product is intentionally simpler now:

- explorer emphasizes tasks, frontier, and activity
- verification and disputes still exist
- global reputation is not the main UX

That keeps launch centered on:

- tasks
- experiments
- verification
- artifacts
- sync
