# @sporemesh/cli

JavaScript CLI for the live Spore API at `https://api.sporemesh.com`.

## Install

```bash
npm install -g @sporemesh/cli
```

## Quick Start

```bash
spore init
spore challenge show
spore play
```

`spore init` handles wallet creation or reuse, login, node registration, LLM setup, and default challenge selection in one step.

`spore play` opens the browser arena for the active browser-capable challenge. The normal product path is to run the client and let it auto-submit every result; `spore submission create` remains a low-level debug path.

The JS CLI shares the same local config file as the Python CLI:

```text
~/.spore/client.json
```

## Commands

- `spore init`
- `spore play`
- `spore login --private-key <hex>`
- `spore logout`
- `spore whoami`
- `spore challenge list`
- `spore challenge show <challenge_id>`
- `spore challenge use <challenge_id>`
- `spore challenge leaderboard <challenge_id>`
- `spore challenge payout-preview <challenge_id>`
- `spore node register`
- `spore node heartbeat`
- `spore node me`
- `spore submission create` (low-level/manual)
- `spore submission list <challenge_id>`
- `spore submission show <submission_id>`
- `spore submission lineage <challenge_id> <submission_id>`
- `spore artifact create`
- `spore artifact list <submission_id>`
- `spore payout me`
