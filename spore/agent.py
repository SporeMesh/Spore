"""Agent coordination — frontier-aware experiment selection.

Each agent reads the collective research graph before deciding what to try next.
This module handles parent selection, context building, duplicate detection,
and exploration/exploitation balancing.
"""

from __future__ import annotations

import difflib
import random
from dataclasses import dataclass

from .graph import ResearchGraph
from .record import ExperimentRecord, Status


@dataclass
class ExperimentContext:
    """Context provided to an LLM agent for proposing the next experiment."""

    parent_code: str
    parent_record: ExperimentRecord
    recent_improvement: list[ExperimentRecord]
    recent_failure: list[ExperimentRecord]
    sibling: list[ExperimentRecord]
    cross_branch_insight: list[str]
    frontier_summary: str
    graph_stats: dict


@dataclass
class CoordinatorConfig:
    exploit_ratio: float = 0.7  # Probability of exploiting best frontier
    explore_ratio: float = 0.3  # Probability of exploring under-explored branches
    context_window: int = 10  # Number of recent experiments to include
    similarity_threshold: float = 0.8  # Dedup threshold (0-1)
    adaptive: bool = True  # Adapt explore/exploit based on graph state


class AgentCoordinator:
    """Coordinates experiment selection across the swarm."""

    def __init__(self, graph: ResearchGraph, config: CoordinatorConfig | None = None):
        self.graph = graph
        self.config = config or CoordinatorConfig()

    def select_parent(
        self, gpu_class: str | None = None, task_id: str | None = None
    ) -> ExperimentRecord | None:
        """Select which experiment to build on next.

        70% exploit (best frontier), 30% explore (under-explored branches).
        Ratios adapt based on graph state if adaptive=True.
        """
        frontier = (
            self.graph.frontier_by_task(task_id, gpu_class=gpu_class)
            if task_id
            else self.graph.frontier(gpu_class=gpu_class)
        )
        if not frontier:
            return None

        exploit_ratio, explore_ratio = self._get_ratios(frontier)

        if random.random() < exploit_ratio:
            return self._exploit(frontier)
        else:
            return self._explore(frontier)

    def build_context(
        self,
        parent: ExperimentRecord,
        code_lookup: dict[str, str] | None = None,
    ) -> ExperimentContext:
        """Build the context dict that gets fed to the LLM agent.

        Args:
            parent: The selected parent experiment.
            code_lookup: Optional mapping of code_cid -> code content.
        """
        n = self.config.context_window

        # Get parent's code (if available)
        parent_code = ""
        if code_lookup and parent.code_cid in code_lookup:
            parent_code = code_lookup[parent.code_cid]

        # Recent improvements in this branch
        improvements = self._recent_keeps(parent, n)

        # Recent failures from this parent
        failures = self._recent_discards(parent, n)

        # Sibling experiments (what others tried from this parent)
        siblings = self.graph.children(parent.id)

        # Cross-branch insights
        insights = self._cross_branch_insights(parent)

        # Frontier summary
        frontier = (
            self.graph.frontier_by_task(parent.task_id)
            if getattr(parent, "task_id", "")
            else self.graph.frontier()
        )
        summary = self._frontier_summary(frontier)

        # Graph statistics
        stats = {
            "total_experiments": self.graph.count(),
            "frontier_size": len(frontier),
            "best_val_bpb": frontier[0].val_bpb if frontier else None,
            "parent_val_bpb": parent.val_bpb,
            "parent_depth": parent.depth,
            "siblings_tried": len(siblings),
            "siblings_kept": sum(
                1
                for s in siblings
                if (
                    s.status == Status.KEEP
                    if isinstance(s.status, Status)
                    else s.status == "keep"
                )
            ),
        }

        return ExperimentContext(
            parent_code=parent_code,
            parent_record=parent,
            recent_improvement=improvements,
            recent_failure=failures,
            sibling=siblings,
            cross_branch_insight=insights,
            frontier_summary=summary,
            graph_stats=stats,
        )

    def is_duplicate(
        self,
        proposed_diff: str,
        parent_id: str,
    ) -> bool:
        """Check if a similar experiment already exists from this parent.

        Uses SequenceMatcher for fuzzy diff comparison.
        """
        siblings = self.graph.children(parent_id)
        for sibling in siblings:
            similarity = self._diff_similarity(proposed_diff, sibling.diff)
            if similarity > self.config.similarity_threshold:
                return True
        return False

    def format_prompt(self, context: ExperimentContext) -> str:
        """Format the context into a prompt string for the LLM agent."""
        sections = []

        # Current state
        sections.append("## Current State")
        sections.append(f"- Parent val_bpb: {context.parent_record.val_bpb:.6f}")
        sections.append(f"- Parent depth: {context.parent_record.depth}")
        sections.append(
            f"- Total experiments in graph: {context.graph_stats['total_experiments']}"
        )
        if context.graph_stats["best_val_bpb"] is not None:
            sections.append(
                f"- Best val_bpb in network: {context.graph_stats['best_val_bpb']:.6f}"
            )

        # Recent successes
        if context.recent_improvement:
            sections.append("\n## Recent Improvements (what worked)")
            for r in context.recent_improvement[:5]:
                delta = context.parent_record.val_bpb - r.val_bpb
                sections.append(
                    f"- [{r.id[:8]}] {r.description} (val_bpb={r.val_bpb:.6f}, delta={delta:+.6f})"
                )

        # Recent failures
        if context.recent_failure:
            sections.append("\n## Recent Failures (what didn't work)")
            for r in context.recent_failure[:5]:
                sections.append(
                    f"- [{r.id[:8]}] {r.description} (val_bpb={r.val_bpb:.6f})"
                )

        # What siblings tried
        if context.sibling:
            sections.append(
                f"\n## Already Tried from This Parent ({len(context.sibling)} experiments)"
            )
            for s in context.sibling[:10]:
                status_str = (
                    s.status.value if isinstance(s.status, Status) else s.status
                )
                sections.append(f"- [{status_str}] {s.description}")

        # Cross-branch insights
        if context.cross_branch_insight:
            sections.append("\n## Insights from Other Branches")
            for insight in context.cross_branch_insight:
                sections.append(f"- {insight}")

        # Frontier
        if context.frontier_summary:
            sections.append("\n## Network Frontier")
            sections.append(context.frontier_summary)

        # Code
        if context.parent_code:
            sections.append("\n## Current train.py")
            sections.append(f"```python\n{context.parent_code}\n```")

        sections.append("\n## Task")
        sections.append(
            "Propose a single modification to train.py that will lower val_bpb. "
            "Explain your hypothesis and provide the code diff."
        )

        return "\n".join(sections)

    # --- Private methods ---

    def _exploit(self, frontier: list[ExperimentRecord]) -> ExperimentRecord:
        """Pick the best frontier experiment."""
        return min(frontier, key=lambda e: e.val_bpb)

    def _explore(self, frontier: list[ExperimentRecord]) -> ExperimentRecord:
        """Pick an under-explored frontier experiment.

        Weights by: fewer children = more interesting, older = more interesting.
        """
        if len(frontier) == 1:
            return frontier[0]

        scores = []
        for exp in frontier:
            children = self.graph.children(exp.id)
            child_count = len(children)
            # Fewer children → higher score
            score = 1.0 / (1 + child_count)
            scores.append(score)

        total = sum(scores)
        if total == 0:
            return random.choice(frontier)

        weights = [s / total for s in scores]
        return random.choices(frontier, weights=weights, k=1)[0]

    def _get_ratios(self, frontier: list[ExperimentRecord]) -> tuple[float, float]:
        """Adapt explore/exploit ratios based on graph state."""
        if not self.config.adaptive:
            return self.config.exploit_ratio, self.config.explore_ratio

        total = self.graph.count()

        if total < 10:
            # Early: explore more
            return 0.5, 0.5
        elif total < 50:
            return 0.6, 0.4
        else:
            # Check if frontier is plateaued
            best = frontier[0] if frontier else None
            if best:
                recent = self.graph.recent(limit=20)
                recent_improvements = [
                    r
                    for r in recent
                    if (
                        r.status == Status.KEEP
                        if isinstance(r.status, Status)
                        else r.status == "keep"
                    )
                    and r.val_bpb < best.val_bpb * 1.01
                ]
                if len(recent_improvements) < 2:
                    # Plateaued: explore much more
                    return 0.3, 0.7

        return self.config.exploit_ratio, self.config.explore_ratio

    def _recent_keeps(self, parent: ExperimentRecord, n: int) -> list[ExperimentRecord]:
        """Get recent 'keep' experiments in this branch."""
        ancestors = self.graph.ancestors(parent.id)
        keeps = [
            a
            for a in ancestors
            if (
                a.status == Status.KEEP
                if isinstance(a.status, Status)
                else a.status == "keep"
            )
        ]
        return keeps[:n]

    def _recent_discards(
        self, parent: ExperimentRecord, n: int
    ) -> list[ExperimentRecord]:
        """Get recent 'discard' experiments from this parent."""
        children = self.graph.children(parent.id)
        discards = [
            c
            for c in children
            if (
                c.status == Status.DISCARD
                if isinstance(c.status, Status)
                else c.status == "discard"
            )
        ]
        return discards[:n]

    def _cross_branch_insights(self, current_parent: ExperimentRecord) -> list[str]:
        """Summarize successful experiments from other branches."""
        frontier = self.graph.frontier()
        insights = []

        for exp in frontier:
            if exp.id == current_parent.id:
                continue
            # Walk ancestors to find what worked
            ancestors = self.graph.ancestors(exp.id)
            for a in ancestors[:3]:  # Last 3 ancestors of each frontier exp
                if a.id == current_parent.id:
                    break  # Same branch
                if (
                    a.status == Status.KEEP
                    if isinstance(a.status, Status)
                    else a.status == "keep"
                ):
                    insights.append(
                        f"Branch {exp.id[:8]}: {a.description} "
                        f"(val_bpb={a.val_bpb:.6f})"
                    )

        return insights[:10]

    def _frontier_summary(self, frontier: list[ExperimentRecord]) -> str:
        """Summarize the current frontier."""
        if not frontier:
            return "No frontier experiments."

        lines = []
        for exp in frontier[:5]:
            lines.append(
                f"  {exp.id[:8]}: val_bpb={exp.val_bpb:.6f}, "
                f"depth={exp.depth}, gpu={exp.gpu_model}"
            )
        return "\n".join(lines)

    @staticmethod
    def _diff_similarity(diff_a: str, diff_b: str) -> float:
        """Compute similarity between two diffs (0-1)."""
        if not diff_a and not diff_b:
            return 1.0
        if not diff_a or not diff_b:
            return 0.0
        return difflib.SequenceMatcher(None, diff_a, diff_b).ratio()
