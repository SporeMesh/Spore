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
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .record import ExperimentRecord, Status

log = logging.getLogger(__name__)


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
        python_cmd: str = "python3",
    ):
        self.workspace = Path(workspace)
        self.time_budget = time_budget
        self.python_cmd = python_cmd

    def run_training(self, train_script: str = "train.py") -> TrainResult:
        """Run the training script and stream progress live.

        The script is expected to output lines containing:
        - val_bpb: <float>
        - peak_vram_mb: <float>
        - num_parameters: <int>
        - step <int>
        """
        script_path = self.workspace / train_script
        if not script_path.exists():
            return TrainResult(error=f"Script not found: {script_path}", log_output="")

        log_path = self.workspace / "run.log"
        start_time = time.time()
        timeout = self.time_budget + 300  # Extra margin for torch.compile warmup
        output_lines: list[str] = []

        try:
            proc = subprocess.Popen(
                [self.python_cmd, "-u", str(script_path)],
                cwd=str(self.workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                output_lines.append(line)

                # Stream training progress
                if line.startswith("\rstep ") or line.startswith("step "):
                    # Carriage-return progress line from train.py
                    log.info("  %s", line.lstrip("\r").strip())
                elif "compiling" in line.lower() or "compile" in line.lower():
                    log.info("  Compiling model (first run is slow)...")
                elif line.startswith("Estimated") or line.startswith("num_param"):
                    log.info("  %s", line)
                elif line.startswith("Time budget"):
                    log.info("  %s", line)
                elif line.startswith("Gradient"):
                    log.info("  %s", line)
                elif "val_bpb" in line and "step" not in line:
                    log.info("  %s", line)

                # Check timeout
                if time.time() - start_time > timeout:
                    proc.kill()
                    proc.wait()
                    return TrainResult(
                        training_sec=time.time() - start_time,
                        error="Training timed out",
                        log_output="\n".join(output_lines),
                    )

            proc.wait()
            elapsed = time.time() - start_time
            output = "\n".join(output_lines)

            # Save log
            log_path.write_text(output)

            # Parse output
            parsed = self._parse_output(output)
            parsed.training_sec = elapsed
            parsed.log_output = output
            parsed.success = proc.returncode == 0 and parsed.val_bpb > 0

            if not parsed.success and proc.returncode != 0:
                lines = [l for l in output.strip().splitlines() if l.strip()]
                parsed.error = "\n".join(lines[-5:]) if lines else "Unknown error"

            return parsed

        except Exception as e:
            return TrainResult(error=str(e), log_output="\n".join(output_lines))

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

        # val_bpb
        match = re.search(r"val_bpb:\s*([\d.]+)", output)
        if match:
            result.val_bpb = float(match.group(1))

        # peak_vram_mb
        match = re.search(r"peak_vram_mb:\s*([\d.]+)", output)
        if match:
            result.peak_vram_mb = float(match.group(1))

        # num_parameters
        match = re.search(r"num_parameters:\s*([\d,]+)", output)
        if match:
            result.num_params = int(match.group(1).replace(",", ""))

        # step (take the last one)
        steps = re.findall(r"step\s+(\d+)", output)
        if steps:
            result.num_steps = int(steps[-1])

        return result
