"""Task-oriented CLI commands."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .node import SPORE_DIR, NodeConfig, SporeNode

console = Console()


def _close_node(node: SporeNode):
    node.graph.close()
    node.profile.close()
    node.control.close()
    node.task.close()
    node.reputation.close()


def register_command(cli: click.Group):
    """Register task commands on the main CLI."""

    @cli.group()
    def task():
        """Create, list, show, and select tasks."""

    @task.command("list")
    @click.option(
        "--data-dir", "-d", default=None, help="Data directory (default: ~/.spore)"
    )
    def task_list(data_dir: str | None):
        from .cli import ensure_initialized

        data_path = Path(data_dir).expanduser() if data_dir else SPORE_DIR
        ensure_initialized(data_path)
        node = SporeNode(NodeConfig.load(data_path / "config.toml"))
        try:
            tasks = node.all_tasks()
            if not tasks:
                console.print("No tasks known.")
                return
            table = Table(show_header=True)
            table.add_column("Task", style="cyan")
            table.add_column("Name")
            table.add_column("Type")
            table.add_column("Metric")
            table.add_column("Source")
            for item in tasks:
                table.add_row(
                    item["task_id"][:8] + "..",
                    item["name"],
                    item["task_type"] or "legacy",
                    item["metric"] or "—",
                    item["source"],
                )
            console.print(table)
        finally:
            _close_node(node)

    @task.command("show")
    @click.argument("task_id")
    @click.option(
        "--data-dir", "-d", default=None, help="Data directory (default: ~/.spore)"
    )
    def task_show(task_id: str, data_dir: str | None):
        from .cli import ensure_initialized

        data_path = Path(data_dir).expanduser() if data_dir else SPORE_DIR
        ensure_initialized(data_path)
        node = SporeNode(NodeConfig.load(data_path / "config.toml"))
        try:
            item = node.get_task(task_id)
            if not item:
                console.print("Task not found.")
                return
            for key in (
                "task_id",
                "name",
                "description",
                "task_type",
                "artifact_type",
                "metric",
                "goal",
                "root_experiment_id",
                "created_by",
                "timestamp",
                "source",
            ):
                console.print(f"{key}: {item.get(key, '')}")
        finally:
            _close_node(node)

    @task.command("use")
    @click.argument("task_id")
    @click.option(
        "--data-dir", "-d", default=None, help="Data directory (default: ~/.spore)"
    )
    def task_use(task_id: str, data_dir: str | None):
        from .cli import ensure_initialized

        data_path = Path(data_dir).expanduser() if data_dir else SPORE_DIR
        ensure_initialized(data_path)
        node = SporeNode(NodeConfig.load(data_path / "config.toml"))
        try:
            if node.get_task(task_id) is None:
                raise click.ClickException("Unknown task_id")
            node.set_active_task(task_id)
            console.print(f"Active task set to [cyan]{task_id}[/]")
        finally:
            _close_node(node)

    @task.command("create")
    @click.option("--name", required=True, help="Task name")
    @click.option("--description", default="", help="Task description")
    @click.option("--task-type", default="ml_train", help="Task type")
    @click.option(
        "--artifact-type", default="python_train_script", help="Artifact type"
    )
    @click.option("--metric", default="val_bpb", help="Primary metric")
    @click.option("--goal", default="minimize", help="Optimization goal")
    @click.option("--base-code-cid", default="", help="Baseline code CID")
    @click.option("--prepare-cid", default="", help="Preparation/evaluator CID")
    @click.option("--dataset-cid", default="", help="Dataset CID")
    @click.option("--time-budget", default=300, type=int, help="Per-run time budget")
    @click.option(
        "--data-dir", "-d", default=None, help="Data directory (default: ~/.spore)"
    )
    def task_create(
        name: str,
        description: str,
        task_type: str,
        artifact_type: str,
        metric: str,
        goal: str,
        base_code_cid: str,
        prepare_cid: str,
        dataset_cid: str,
        time_budget: int,
        data_dir: str | None,
    ):
        from .cli import ensure_initialized

        data_path = Path(data_dir).expanduser() if data_dir else SPORE_DIR
        ensure_initialized(data_path)
        node = SporeNode(NodeConfig.load(data_path / "config.toml"))
        try:
            manifest = node.create_task(
                name=name,
                description=description,
                task_type=task_type,
                artifact_type=artifact_type,
                metric=metric,
                goal=goal,
                base_code_cid=base_code_cid,
                prepare_cid=prepare_cid,
                dataset_cid=dataset_cid,
                time_budget=time_budget,
            )
            console.print(f"Created task [cyan]{manifest.task_id}[/]")
            console.print(
                "Task will gossip on the next `spore run` or `spore explorer`."
            )
        finally:
            _close_node(node)
