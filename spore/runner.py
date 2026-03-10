"""Experiment runner — drives train.py, captures results, produces records.

Orchestrates the experiment loop:
1. Select parent experiment (via agent coordinator)
2. Apply proposed code modification
3. Run training with timeout
4. Parse results
5. Construct and publish ExperimentRecord
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from .record import ExperimentRecord, Status

log = logging.getLogger(__name__)
console = Console()


@dataclass
class TrainResult:
    """Parsed output from a training run."""

    val_bpb: float = 0.0
    peak_vram_mb: float = 0.0
    num_steps: int = 0
    num_params: int = 0
    training_sec: float = 0.0
    success: bool = False
    log_output: str = ""
    error: str = ""


class ExperimentRunner:
    """Runs training experiments and captures results."""

    def __init__(
        self,
        workspace: str | Path,
        time_budget: int = 300,
        python_cmd: str | None = None,
    ):
        self.workspace = Path(workspace)
        self.time_budget = time_budget
        self.python_cmd = python_cmd or sys.executable
        self._compile_disabled = False

    def run_training(self, train_script: str = "train.py") -> TrainResult:
        """Run the training script with live progress display."""
        if self._compile_disabled:
            return self._run_training_once(
                train_script,
                env_overrides={
                    "SPORE_DISABLE_COMPILE": "1",
                    "TORCHINDUCTOR_COMPILE_THREADS": "1",
                },
            )

        result = self._run_training_once(train_script)
        if result.success or not self._looks_like_compile_crash(result):
            return result

        console.print(
            "[yellow]Compile crash detected, retrying with compile disabled.[/]"
        )
        self._compile_disabled = True
        retry_result = self._run_training_once(
            train_script,
            env_overrides={
                "SPORE_DISABLE_COMPILE": "1",
                "TORCHINDUCTOR_COMPILE_THREADS": "1",
            },
        )
        if retry_result.success:
            retry_result.log_output = (
                result.log_output
                + "\n\n=== retry: compile disabled ===\n\n"
                + retry_result.log_output
            )
            return retry_result
        if result.log_output or retry_result.log_output:
            retry_result.log_output = (
                result.log_output
                + "\n\n=== retry: compile disabled ===\n\n"
                + retry_result.log_output
            )
        return retry_result

    def _run_training_once(
        self,
        train_script: str = "train.py",
        env_overrides: dict[str, str] | None = None,
    ) -> TrainResult:
        """Run the training script once with optional environment overrides."""
        script_path = self.workspace / train_script
        if not script_path.exists():
            return TrainResult(error=f"Script not found: {script_path}", log_output="")

        log_path = self.workspace / "run.log"
        start_time = time.time()
        timeout = self.time_budget + 300
        output_lines: list[str] = []

        # Live state
        phase = "Initializing"
        cur_step = 0
        cur_loss = 0.0
        cur_speed = ""
        cur_remaining = self.time_budget
        cur_pct = 0.0
        cur_epoch = 0

        try:
            env = os.environ.copy()
            if env_overrides:
                env.update(env_overrides)
            proc = subprocess.Popen(
                [self.python_cmd, "-u", str(script_path)],
                cwd=str(self.workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold]{task.description}"),
                BarColumn(bar_width=30),
                TextColumn("[cyan]{task.fields[pct]}[/]"),
                TextColumn("remaining [dim]{task.fields[eta]}[/]"),
                console=console,
                transient=True,
            )
            task_id = progress.add_task(
                "Training", total=self.time_budget, pct="0%", eta=f"{self.time_budget}s"
            )

            def _build_panel() -> Panel:
                grid = Table.grid(padding=(0, 2))
                grid.add_column(style="dim", width=10)
                grid.add_column()
                grid.add_row("Phase", f"[bold]{phase}[/]")
                if cur_step > 0:
                    grid.add_row("Step", str(cur_step))
                    grid.add_row("Loss", f"[yellow]{cur_loss:.4f}[/]")
                    if cur_speed:
                        grid.add_row("Speed", cur_speed)
                    grid.add_row("Epoch", str(cur_epoch))
                return Panel(
                    grid, title="[bold]Experiment[/]", border_style="blue", expand=False
                )

            assert proc.stdout is not None
            with Live(
                _build_panel(), console=console, refresh_per_second=4, transient=True
            ) as live:
                for line in proc.stdout:
                    line = line.rstrip("\n").lstrip("\r")
                    output_lines.append(line)

                    # Parse step lines
                    step_match = re.match(
                        r"step\s+(\d+)\s+\(([\d.]+)%\)\s+\|"
                        r"\s+loss:\s+([\d.]+)\s+\|"
                        r".*?tok/sec:\s+([\d,]+)\s+\|"
                        r".*?epoch:\s+(\d+)\s+\|"
                        r"\s+remaining:\s+(\d+)s",
                        line,
                    )
                    if step_match:
                        phase = "Training"
                        cur_step = int(step_match.group(1))
                        cur_pct = float(step_match.group(2))
                        cur_loss = float(step_match.group(3))
                        cur_speed = f"{step_match.group(4)} tok/s"
                        cur_epoch = int(step_match.group(5))
                        cur_remaining = int(step_match.group(6))
                        elapsed_train = self.time_budget - cur_remaining
                        progress.update(
                            task_id,
                            completed=elapsed_train,
                            pct=f"{cur_pct:.1f}%",
                            eta=f"{cur_remaining}s",
                        )
                    elif "compiling" in line.lower() or "compile" in line.lower():
                        phase = "Compiling (first run is slow)"
                    elif "val_bpb" in line and "step" not in line:
                        phase = "Evaluating"

                    live.update(_build_panel())

                    if time.time() - start_time > timeout:
                        proc.kill()
                        proc.wait()
                        return TrainResult(
                            training_sec=time.time() - start_time,
                            error="Training timed out",
                            log_output="\n".join(output_lines),
                        )

                progress.update(
                    task_id, completed=self.time_budget, pct="100%", eta="0s"
                )

            proc.wait()
            elapsed = time.time() - start_time
            output = "\n".join(output_lines)

            log_path.write_text(output)

            parsed = self._parse_output(output)
            parsed.training_sec = elapsed
            parsed.log_output = output
            parsed.success = proc.returncode == 0 and parsed.val_bpb > 0

            if not parsed.success and proc.returncode != 0:
                lines = [l for l in output.strip().splitlines() if l.strip()]
                if proc.returncode < 0:
                    sig = -proc.returncode
                    try:
                        sig_name = signal.Signals(sig).name
                    except ValueError:
                        sig_name = "UNKNOWN"
                    tail = "\n".join(lines[-5:]) if lines else ""
                    parsed.error = (
                        f"Process terminated by signal {sig} ({sig_name})"
                        + (f"\n{tail}" if tail else "")
                    )
                else:
                    parsed.error = "\n".join(lines[-5:]) if lines else "Unknown error"

            # Print result summary
            if parsed.success:
                result_text = Text()
                result_text.append("val_bpb ", style="dim")
                result_text.append(f"{parsed.val_bpb:.6f}", style="bold green")
                result_text.append("  steps ", style="dim")
                result_text.append(str(parsed.num_steps), style="cyan")
                result_text.append("  vram ", style="dim")
                result_text.append(f"{parsed.peak_vram_mb:.0f}MB", style="cyan")
                result_text.append(f"  {elapsed:.0f}s", style="dim")
                console.print(
                    Panel(
                        result_text,
                        title="[bold green]Complete[/]",
                        border_style="green",
                        expand=False,
                    )
                )
            else:
                console.print(
                    Panel(
                        f"[red]{parsed.error or 'Unknown error'}[/]",
                        title="[bold red]Failed[/]",
                        border_style="red",
                        expand=False,
                    )
                )

            return parsed

        except Exception as e:
            return TrainResult(error=str(e), log_output="\n".join(output_lines))

    def _looks_like_compile_crash(self, result: TrainResult) -> bool:
        """Return True if the failure matches a known torch.compile/Inductor crash."""
        haystack = "\n".join(
            part for part in (result.error, result.log_output) if part
        ).lower()
        return any(
            token in haystack
            for token in (
                "torch._inductor.exc.inductorerror",
                "a compilation subprocess exited unexpectedly",
                "torchinductor_compile_threads=1",
                'set torch_logs="+dynamo"',
            )
        )

    def apply_code(self, code: str, train_script: str = "train.py"):
        """Write new code to the training script."""
        script_path = self.workspace / train_script
        script_path.write_text(code)

    def get_code(self, train_script: str = "train.py") -> str:
        """Read the current training script."""
        script_path = self.workspace / train_script
        if script_path.exists():
            return script_path.read_text()
        return ""

    def get_code_cid(self, train_script: str = "train.py") -> str:
        """Compute CID of the current training script."""
        code = self.get_code(train_script)
        return hashlib.sha256(code.encode()).hexdigest()

    def make_record(
        self,
        result: TrainResult,
        parent: ExperimentRecord | None,
        diff: str,
        description: str,
        hypothesis: str,
        agent_model: str,
        dataset_cid: str,
        prepare_cid: str,
        node_id: str,
        gpu_model: str = "unknown",
        cuda_version: str = "unknown",
        torch_version: str = "unknown",
    ) -> ExperimentRecord:
        """Create an ExperimentRecord from a training result."""
        if result.success:
            status = (
                Status.KEEP
                if parent is None or result.val_bpb < parent.val_bpb
                else Status.DISCARD
            )
        elif result.error:
            status = Status.CRASH
        else:
            status = Status.DISCARD

        return ExperimentRecord(
            parent=parent.id if parent else None,
            depth=(parent.depth + 1) if parent else 0,
            code_cid=self.get_code_cid(),
            diff=diff,
            dataset_cid=dataset_cid,
            prepare_cid=prepare_cid,
            time_budget=self.time_budget,
            val_bpb=result.val_bpb,
            peak_vram_mb=result.peak_vram_mb,
            num_steps=result.num_steps,
            num_params=result.num_params,
            status=status,
            description=description,
            hypothesis=hypothesis,
            agent_model=agent_model,
            gpu_model=gpu_model,
            cuda_version=cuda_version,
            torch_version=torch_version,
            node_id=node_id,
        )

    def _parse_output(self, output: str) -> TrainResult:
        """Parse training script output for metrics."""
        result = TrainResult()

        match = re.search(r"val_bpb:\s*([\d.]+)", output)
        if match:
            result.val_bpb = float(match.group(1))

        match = re.search(r"peak_vram_mb:\s*([\d.]+)", output)
        if match:
            result.peak_vram_mb = float(match.group(1))

        match = re.search(r"num_parameters:\s*([\d,]+)", output)
        if match:
            result.num_params = int(match.group(1).replace(",", ""))
        else:
            match = re.search(r"num_params_M:\s*([\d.]+)", output)
            if match:
                result.num_params = int(float(match.group(1)) * 1_000_000)

        match = re.search(r"num_steps:\s*(\d+)", output)
        if match:
            result.num_steps = int(match.group(1))
        else:
            steps = re.findall(r"step\s+(\d+)", output)
            if steps:
                result.num_steps = int(steps[-1])

        return result
