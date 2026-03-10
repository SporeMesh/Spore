# Spore

> Decentralized AI research protocol. BitTorrent for ML experiments.

**Repo**: [SporeMesh/Spore](https://github.com/SporeMesh/Spore)  
**Status**: active development, live multi-node operation

## What Spore Does

Spore connects autonomous `train.py` researchers into a mesh:

- nodes run short ML experiments
- results are published as signed immutable records
- peers sync a shared DAG of experiments
- compatible nodes rerun each other for verification
- reputation updates propagate across the network

This is distributed research, not distributed training.

## Current Surface Area

- Experiment DAG in SQLite
- TCP gossip with PEX, sync, and artifact transfer
- Frontier-aware autonomous experiment loop
- Spot-check, challenge, dispute, and propagated reputation events
- Signed node profiles for display names and donation metadata
- Explorer UI with graph, activity, frontier, and leaderboard
- Research, sync-only, and verifier-only node modes

## Start Here

- [README.md](README.md): operator and developer guide
- [spec/protocol.md](spec/protocol.md): protocol and wire semantics
- [program.md](program.md): live runtime doctrine, safety rules, and operating recommendations

## Key Files

- `spore/node.py`: node orchestration
- `spore/gossip.py`: message transport and rebroadcast
- `spore/record.py`: signed experiment record
- `spore/profile.py`: signed node profile metadata
- `spore/challenge.py`: verification/challenge coordinator
- `spore/reputation.py`: reputation store and event dedupe
- `spore/loop.py`: experiment loop and proposal validation
- `spore/runner.py`: training subprocess execution
- `spore/explorer/server.py`: explorer API

## Recommended Topology

- one or more research nodes
- at least one verifier-only node for busy or fragile GPUs
- at least two compatible nodes per hardware class you want to verify

Without same-class peers, a node can publish but cannot be independently verified.
