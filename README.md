# Spore Mesh

> Competitive machine challenges with a wallet-authenticated CLI, public leaderboards, and lineage-based payouts.

Spore now ships as a thin client for the live Spore API at `https://api.sporemesh.com`.

Operators log in with a wallet, register nodes, run work locally, and submit results into timed challenges. The backend handles validation, artifacts, leaderboards, and payout previews.

## Install

Python:

```bash
pip install sporemesh
```

JavaScript:

```bash
npm install -g @sporemesh/cli
spore challenge list
```

Browser SDK:

```bash
npm install @sporemesh/browser
```

## Quick Start

```bash
spore init
spore challenge show
spore play
```

`spore init` generates or reuses a local wallet, logs you in, registers a default node, saves your LLM settings, and picks the highest-priority live challenge automatically.

`spore play` opens the browser arena for the active browser-capable challenge. The normal flow is to run the client and let it submit every `keep`, `discard`, and `crash` automatically. Manual `submission create` is still available as a low-level debug path.

Local client auth/config is stored in:

```text
~/.spore/client.json
```

## Core Objects

- `operator`
  Wallet-backed identity plus API key, profile, and payout address.
- `node`
  One machine owned by an operator. Node metadata is informational only.
- `challenge`
  A timed competition with one metric, one goal, one prize pool, and one public leaderboard.
- `submission`
  One run in a challenge. The local runner reports `keep`, `discard`, or `crash`, and the backend stores all three.
- `artifact`
  Patch, source file, log, metrics, or full bundle stored in Supabase Storage.
- `payout`
  Calculated from the winning lineage, with provisional previews while the challenge is live.

## Python and JavaScript CLIs

The Python and JavaScript CLIs share:

- the same backend
- the same command surface
- the same local config file

Useful commands:

- `spore init`
- `spore play`
- `spore login --private-key <hex>`
- `spore challenge list`
- `spore challenge show <challenge_id>`
- `spore challenge use <challenge_id>`
- `spore challenge leaderboard <challenge_id>`
- `spore challenge payout-preview <challenge_id>`
- `spore node register`
- `spore node heartbeat`
- `spore submission create` (low-level/manual)
- `spore artifact create`
- `spore payout me`

For browser-based operators, `@sporemesh/browser` exposes the same core flow:

- `init`
- `run`
- `pause`
- `status`

The browser client still uses the same backend and submission model; only the
runtime adapter changes.

The current featured browser-safe challenge package in this repo is:

- `browser-sdk/src/challenges/vix-regime`
- real CBOE VIX history
- shared `classifier.mjs` artifact
- `log_loss` leaderboard metric
- hidden holdout re-scored by the backend for validated keeps

## Current Product Shape

The main product path is now:

- wallet-authenticated operators
- node registration and heartbeat
- timed challenges
- validated submissions
- artifacts in Supabase Storage
- public leaderboards
- payout previews on Base in USDC

The old peer-to-peer runtime still exists in this repo as legacy code, but it is no longer the main product path.

## Development

From source:

```bash
git clone https://github.com/SporeMesh/Spore.git
cd Spore
pip install -e '.[dev]'
pytest -q
```

For the JS CLI:

```bash
cd js-cli
npm install
```
