# Spore Program

This file describes the current operating doctrine for a live Spore network.

It is not the wire spec. It is the practical program: how nodes are expected to behave, what safety rules exist locally, and how to run the network without self-inflicted failure.

## 1. Goal

Spore exists to discover better `train.py` variants through many cheap, verifiable experiments.

The network should optimize for:

- more valid experiments
- faster convergence on useful code
- cheap independent reruns
- low operational fragility
- identity and attribution without turning metadata into consensus

## 2. Node Roles

Spore currently supports three useful node roles.

### 2.1 Research Node

`spore run`

Responsibilities:

- sync the graph
- fetch frontier code
- ask the configured LLM for the next candidate
- run local experiments
- publish records and code artifacts
- verify compatible remote experiments if a workspace exists

### 2.2 Verifier-Only Node

`spore run --verify-only`

Responsibilities:

- sync the graph
- prepare the workspace
- fetch code artifacts
- rerun compatible experiments
- participate in challenges and disputes

Use this when you want a GPU to spend its time stabilizing the network instead of generating new proposals.

### 2.3 Sync-Only Node

`spore run --no-train`

Responsibilities:

- sync the graph
- gossip data
- optionally host explorer surfaces

This is not enough for verification because no training workspace is attached.

## 3. Identity

The protocol identity is the Ed25519 `node_id`.

Everything consensus-relevant ties to that:

- experiment signatures
- challenge participation
- verification credit
- dispute outcomes
- reputation accounting

Presentation metadata is separate.

## 4. Node Profile Metadata

Profiles are signed side-channel metadata, not protocol identity.

Fields:

- `display_name`
- `bio`
- `website`
- `avatar_url`
- `donation_address`
- `timestamp`
- `schema_version`

Design rules:

- `display_name`, not `username`
- no protocol-level uniqueness
- no profile field affects reputation or verification
- wallet and donation metadata are optional and replaceable later

This lets explorers show human-readable labels without creating name-squatting or identity-recovery problems.

## 5. Experiment Program

The local research loop is:

1. sync the graph
2. identify the best compatible frontier
3. fetch and apply the frontier code
4. ask the LLM for a full replacement `train.py`
5. validate the returned code locally
6. run training
7. publish result and code snapshot
8. keep or revert locally

This program is intentionally simple. Spore should improve by many cheap experiments, not by making the control plane cleverer than the research itself.

## 6. Local Proposal Safety Policy

Generated code should not be trusted just because it parses.

Current local policy rejects candidates that:

- use obviously broken identifiers like `MAX_SEQ_SIZE`
- introduce forbidden runtime features such as `subprocess`, `multiprocessing`, `socket`, `ctypes`, or process-kill logic
- add new `torch.compile` call sites
- scale model size past the local safe envelope on constrained hardware

On constrained nodes, the policy currently prevents oversized changes to:

- `DEPTH`
- `ASPECT_RATIO`
- `HEAD_DIM`
- `TOTAL_BATCH_SIZE`
- the derived `DEPTH * ASPECT_RATIO` model-width envelope

Reason:

The network should not repeatedly rediscover that a `3060` can crash on ambitious proposals. Local policy should reject bad candidates before they waste GPU time or flood the graph with avoidable crashes.

## 7. Runtime Safety Rules

### 7.1 Compile Policy

Small CUDA cards default to compile-disabled mode. The local runtime sets:

- `SPORE_DISABLE_COMPILE=1`
- `TORCHINDUCTOR_COMPILE_THREADS=1`

This is a stability policy, not a benchmark policy.

### 7.2 Serialized Local Work

One node should not simultaneously:

- run its own research experiment
- run a spot-check
- run challenge verification

Spore now serializes local training work with a single runtime lock.

### 7.3 Isolated Verification Workspace

Spot-checks and challenge verifications run in a temporary copied workspace.

Reason:

- no accidental overwriting of the active `train.py`
- no verification mutation leaking into local research state

## 8. Verification Program

Verification should be cheap, same-class, and attributable.

Current behavior:

- incoming compatible experiments are probabilistically selected for spot-check
- crash records are skipped
- if a rerun is within tolerance, a verification event is propagated
- if it falls outside tolerance, a challenge is opened
- compatible independent verifiers volunteer
- the challenger resolves the dispute after collecting responses or timing out

Important constraints:

- the original publisher is not an independent verifier
- cross-class val_bpb is not authoritative
- no same-class peers means no independent verification

## 9. Reputation Program

Reputation is event-based and idempotent.

That means:

- nodes should be able to receive the same propagated event multiple times
- score changes should only apply once per `event_id`
- explorer views should derive from the accumulated store, not local ephemeral memory

Current score semantics:

- published count is tracked separately and does not itself change score
- successful verification of a record rewards the publisher
- performing a verification rewards the verifier
- dispute winners and losers get asymmetric outcomes

The wrong behavior that used to exist and must never return:

- issuing a challenge by itself must not earn verification credit

## 10. Artifact Program

Records are not enough. Verification needs the exact code snapshot.

Current artifact doctrine:

- code snapshots are content-addressed by `code_cid`
- a node should prefetch code when a remote experiment arrives
- multiple code fetches for the same artifact should share one inflight request
- the fetched bytes must hash back to the requested CID before caching

The practical consequence is important:

experiment gossip can look healthy while verification still fails if artifact availability is weak.

## 11. Hardware Classes

Spore currently uses normalized verification classes rather than raw device names.

Examples:

- `NVIDIA GeForce RTX 3060` and `RTX_3060` normalize to the same class
- Apple Metal devices normalize to `APPLE_MPS`
- CPU-only nodes normalize to `CPU`

This is better than exact-string matching, but it is still an approximation.

Future work should include richer capability bucketing for:

- Apple MPS families
- CPU nodes
- mixed-memory or throughput-variant GPUs

## 12. Resource Control

`--resource N` scales batch size, but only within the runtime assumptions of the applied `train.py`.

Operational guidance:

- `50` and `100` are the safest live settings on fragile research nodes
- arbitrary values like `70` are only safe when the applied frontier code includes the newer batch-snapping logic

This is the important distinction:

- package runtime fixes affect the host
- frontier `train.py` remains experiment content and can carry older assumptions

## 13. Recommended Live Topology

For a small public network:

- one stronger research node on the best available GPU
- one research node on the common commodity class you care about
- one verifier-only node on that commodity class

Example:

- `RTX_5090` research
- `RTX_3060` research
- `RTX_3060` verifier-only

That gives you:

- fresh experiments on both classes
- actual same-class verification on `3060`
- fewer local resource collisions

## 14. Known Operational Limits

Current limitations that operators should understand:

- a lone hardware class cannot be independently verified
- old frontier code can still be unstable even after package fixes
- low-end CUDA hardware can still hit occasional low-level PyTorch/CUDA failures
- profile metadata gossips live and is not yet part of historical state sync

## 15. What Good Looks Like

A healthy Spore network should show:

- non-zero verified experiments
- non-zero verifications performed
- challenges only when same-class disagreement is real
- explorer names resolving from signed profiles
- minimal crash spam from clearly invalid LLM proposals

If the graph is growing but verification and reputation stay flat, the first things to check are:

1. same-class peer availability
2. artifact fetch success
3. verifier runtime stability
4. whether the relevant nodes actually have a workspace and verification path enabled
