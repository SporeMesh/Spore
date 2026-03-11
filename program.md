# Spore Program

This document describes the live operating doctrine for the current implementation.

It is not the wire format. It is the practical program for running the network safely.

## 1. Main Principle

Spore should behave like:

- LimeWire for transport
- signed replayable facts for correctness

Nodes do not need to be online all the time. They do need to exchange durable, signed state when they reconnect.

## 2. Task-Scoped Network

The network is not one global objective anymore.

Rules:

- each experiment belongs to exactly one `task_id`
- parent and child must share the same `task_id`
- each task has its own root, frontier, recent feed, and verification flow
- legacy roots are backfilled into separate legacy tasks automatically

That means “extra roots” are no longer protocol corruption. They are separate tasks unless explicitly created in the same task, which is rejected.

## 3. Node Roles

### Research Node

`spore run`

- sync experiments, tasks, control events, and artifacts
- choose a task or auto-follow the most active known task
- fetch frontier code
- propose and run new experiments
- publish results

### Verifier-Only Node

`spore run --verify-only`

- sync the network
- attach a workspace
- rerun compatible remote experiments
- participate in challenges and disputes

### Sync-Only Node

`spore run --no-train`

- sync and relay all tasks
- serve artifacts
- host explorer if desired

Use this for `peer.sporemesh.com`.

## 4. Research Loop

The local research loop is:

1. sync peers fully
2. choose a task
3. fetch the best compatible frontier inside that task
4. apply the frontier code
5. ask the LLM for a replacement `train.py`
6. reject unsafe proposals locally
7. run the experiment
8. publish the signed result plus code artifact

If the node cannot yet fetch usable frontier code for a non-empty task, it waits and retries. It should not create a stray root inside that task.

## 5. Verification Loop

Verification is:

- task-scoped
- same-class
- signed
- replayable

Rules:

- crash records are skipped
- the original publisher is not an independent verifier
- successful reruns emit signed verification events
- mismatches emit signed challenges
- challenge responses and disputes are signed control events
- control events are stored durably and replay after reconnect

## 6. Artifact Doctrine

Experiment records alone are not enough.

Every meaningful rerun depends on the exact `train.py` snapshot referenced by `code_cid`.

Current policy:

- prefetch artifacts when remote experiments arrive
- share inflight fetches instead of duplicating them
- verify bytes against CID before caching

## 7. Runtime Safety

### Small CUDA GPUs

For `RTX_3060`-class hardware and similar:

- compile is disabled by policy
- research and verification do not overlap on one node
- verification uses an isolated temp workspace
- proposal validation blocks obviously unsafe or oversized edits

Recommended operator settings:

```bash
SPORE_DISABLE_COMPILE=1 spore run --resource 50
SPORE_DISABLE_COMPILE=1 spore run --verify-only --resource 50
```

### Baseline Discipline

Once a task exists, ordinary experiments should have a parent inside that task.

Only the task root is parentless.

## 8. Profiles

Profiles are signed display metadata only.

- `display_name`
- `bio`
- `website`
- `avatar_url`
- `donation_address`

They are useful for explorers and public attribution, but must never affect verification or acceptance.

## 9. Auto-Operator

The built-in operator periodically checks an official release manifest.

Current behavior:

- fetch manifest
- compare versions
- install newer package if one exists
- run a constrained instruction set
- restart `spore run`

This is intentionally narrow. The operator is not a remote shell.

## 10. Public Launch Topology

Recommended launch:

- 1 sync-only public relay
- 1 or more research nodes
- 1 verifier-only node for each fragile or high-traffic hardware class

Practical example:

- AWS CPU box: `spore run --no-train`
- one `3060`: `spore run --verify-only --resource 50`
- research GPUs: `spore run --resource 50`

## 11. Product Focus

For launch, the important things are:

- tasks
- experiments
- frontier
- verification
- disputes
- artifact availability

Global reputation is not the main product claim right now and should not dominate the explorer or operational model.
