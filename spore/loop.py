"""Autonomous experiment loop — the research engine.

Each iteration:
1. Select parent experiment from the frontier
2. Call LLM to propose a train.py modification
3. Run training (~5 min)
4. Publish result to DAG + gossip
5. Revert train.py if val_bpb didn't improve
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import logging
import re
from pathlib import Path

from rich.console import Console

from .agent import AgentCoordinator
from .llm import LLMClient
from .llm import load_config as load_llm_config
from .node import SporeNode
from .runner import ExperimentRunner

log = logging.getLogger(__name__)
console = Console()

SYSTEM_PROMPT = """\
You are an autonomous ML researcher optimizing a language model pretraining script.

Your goal: modify train.py to achieve the lowest possible val_bpb (bits per byte).

Rules:
- You may ONLY modify train.py. prepare.py is read-only.
- Training runs for a fixed 5-minute time budget. Don't worry about speed.
- Do not add new package dependencies.
- Simpler is better. A tiny improvement that adds complexity is not worth it.
- Removing code and getting equal/better results is always a win.
- Everything is fair game: architecture, optimizer, hyperparameters, batch size.

Return the FULL modified train.py inside a ```python code block.
Before the code, write exactly two lines:
Description: <what you changed>
Hypothesis: <why it should improve val_bpb>"""


class ExperimentLoop:
    """Runs autonomous experiments: LLM proposes changes, runner evaluates."""

    def __init__(self, node: SporeNode, workspace: Path):
        self.node = node
        self.workspace = workspace
        self.node.workspace = workspace  # Enable spot-checking
        self.runner = ExperimentRunner(workspace)
        self.coordinator = AgentCoordinator(node.graph)
        self.llm = LLMClient(load_llm_config(node.data_dir))
        self._prepare_cid = self._hash_file("prepare.py")
        self._gpu = _detect_gpu()
        self._cuda_ver = _detect_cuda_version()
        self._torch_ver = _detect_torch_version()

    async def run(self):
        """Run baseline if needed, then experiment forever."""
        await self._await_peer_sync()

        if self.node.graph.count() == 0:
            # No experiments from peers — run baseline
            ok = await self._run_baseline()
            if not ok:
                log.error(
                    "Baseline failed. Is prepare.py data ready? Does train.py run?"
                )
                return
        else:
            # Graph has experiments from peers — fetch best code
            applied = await self._apply_frontier_code()
            if not applied:
                log.info("Could not fetch frontier code, running baseline instead")
                ok = await self._run_baseline()
                if not ok:
                    log.error("Baseline failed.")
                    return

        while True:
            try:
                await self._run_one()
            except Exception:
                log.exception("Experiment iteration failed")
                await asyncio.sleep(10)

    async def _await_peer_sync(self):
        """Wait for peer sync to populate the graph."""
        has_peer = self.node.config.peer or self.node.gossip.peers
        if not has_peer:
            return
        log.info("Waiting for peer sync...")
        for _ in range(30):  # up to 15 seconds
            await asyncio.sleep(0.5)
            if self.node.graph.count() > 0:
                await asyncio.sleep(2.0)  # wait for stragglers
                break
        log.info("Peer sync: %d experiments in graph", self.node.graph.count())

    async def _apply_frontier_code(self) -> bool:
        """Fetch the best frontier experiment's code and apply as train.py."""
        best = self.node.graph.best()
        if best is None:
            return False

        console.print(
            f"[dim]Best frontier: {best.id[:8]} val_bpb={best.val_bpb:.6f}[/]"
        )

        # Check local artifact store first
        code_bytes = self.node.store.get(best.code_cid)
        if code_bytes is None:
            console.print("[dim]Requesting frontier code from peers...[/]")
            code_bytes = await self.node.fetch_code(best.code_cid)

        if code_bytes is None:
            console.print("[yellow]Could not obtain frontier code[/]")
            return False

        code = code_bytes.decode("utf-8")
        self.runner.apply_code(code)
        console.print(
            f"[green]Applied frontier code from {best.id[:8]} "
            f"(val_bpb={best.val_bpb:.6f})[/]"
        )
        return True

    async def _run_baseline(self) -> bool:
        """Run train.py as-is to establish baseline val_bpb."""
        console.print("\n[bold]Running baseline...[/]\n")
        result = await asyncio.to_thread(self.runner.run_training)
        if not result.success:
            console.print(f"[red]Baseline failed: {result.error}[/]")
            return False

        code = self.runner.get_code()
        record = self._make_record(
            result,
            parent=None,
            diff="",
            description="baseline",
            hypothesis="Baseline run of the unmodified training script.",
            agent="baseline",
        )
        await self.node.publish_experiment(record, code=code)
        console.print("[green]Baseline published to graph.[/]\n")
        return True

    async def _run_one(self):
        """One experiment: propose → run → publish → keep/revert."""
        parent = self.coordinator.select_parent()
        if parent is None:
            log.info("No frontier experiments yet, waiting...")
            await asyncio.sleep(30)
            return

        # Build context and ask LLM for a proposal
        current_code = self.runner.get_code()
        context = self.coordinator.build_context(
            parent, {parent.code_cid: current_code}
        )
        prompt = self.coordinator.format_prompt(context)

        console.print(
            f"[dim]Proposing change (parent val_bpb={parent.val_bpb:.6f})...[/]"
        )
        response = await asyncio.to_thread(self.llm.chat, SYSTEM_PROMPT, prompt)

        new_code = _extract_code(response)
        if not new_code:
            console.print("[yellow]LLM response had no code block, skipping[/]")
            return

        # Apply, run, record
        old_code = current_code
        description, hypothesis = _extract_metadata(response)
        console.print(f"\n[bold]Experiment:[/] {description}\n")

        self.runner.apply_code(new_code)
        result = await asyncio.to_thread(self.runner.run_training)

        diff = _compute_diff(old_code, new_code)
        current_code = self.runner.get_code()
        record = self._make_record(
            result,
            parent=parent,
            diff=diff,
            description=description,
            hypothesis=hypothesis,
            agent=self.llm.model,
        )
        await self.node.publish_experiment(record, code=current_code)

        # Keep or revert
        if result.success and result.val_bpb < parent.val_bpb:
            delta = parent.val_bpb - result.val_bpb
            console.print(
                f"[bold green]KEEP[/] val_bpb={result.val_bpb:.6f} [green](improved by {delta:.6f})[/]\n"
            )
        else:
            self.runner.apply_code(old_code)
            if result.success:
                console.print(
                    f"[bold red]DISCARD[/] val_bpb={result.val_bpb:.6f} [dim](parent={parent.val_bpb:.6f})[/]\n"
                )
            else:
                console.print(f"[bold yellow]CRASH[/] {result.error or 'unknown'}\n")

    def _make_record(self, result, parent, diff, description, hypothesis, agent):
        return self.runner.make_record(
            result,
            parent=parent,
            diff=diff,
            description=description,
            hypothesis=hypothesis,
            agent_model=agent,
            node_id=self.node.node_id,
            dataset_cid="climbmix-400b-shuffle",
            prepare_cid=self._prepare_cid,
            gpu_model=self._gpu,
            cuda_version=self._cuda_ver,
            torch_version=self._torch_ver,
        )

    def _hash_file(self, filename: str) -> str:
        path = self.workspace / filename
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _extract_code(response: str) -> str | None:
    """Extract Python code block from LLM response."""
    m = re.search(r"```python\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def _extract_metadata(response: str) -> tuple[str, str]:
    """Extract description and hypothesis from the LLM response."""
    description = ""
    hypothesis = ""
    in_code_block = False

    for line in response.strip().split("\n"):
        line = line.strip()
        lower = line.lower()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if not line or in_code_block or line.startswith("#"):
            continue
        if lower.startswith("description:"):
            description = line.split(":", 1)[1].strip()[:500]
            continue
        if lower.startswith("hypothesis:"):
            hypothesis = line.split(":", 1)[1].strip()[:500]
            continue
        if not description:
            description = line[:500]
        elif not hypothesis:
            hypothesis = line[:500]

    if not description:
        description = "LLM-proposed modification"

    if not hypothesis:
        description, hypothesis = _split_summary(description)

    return description[:500], hypothesis[:500]


def _split_summary(summary: str) -> tuple[str, str]:
    """Best-effort split of a one-line summary into what/why."""
    lower = summary.lower()
    for marker in (" because ", " since ", " so that "):
        idx = lower.find(marker)
        if idx != -1:
            head = summary[:idx].strip(" .")
            tail = summary[idx + len(marker) :].strip(" .")
            return head or summary[:500], tail or summary[:500]
    return summary[:500], summary[:500]


def _compute_diff(old: str, new: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile="train.py",
            tofile="train.py",
            lineterm="",
        )
    )


def _detect_gpu() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_name(0).replace(" ", "_")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "apple-mps"
    except ImportError:
        pass
    return "cpu"


def _detect_torch_version() -> str:
    try:
        import torch

        return torch.__version__
    except ImportError:
        return "unknown"


def _detect_cuda_version() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.version.cuda or "unknown"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"
