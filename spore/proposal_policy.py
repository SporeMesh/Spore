"""Local validation policy for generated train.py proposals."""

from __future__ import annotations

import ast

LOW_VRAM_MODEL_DIM_LIMIT = 512
LOW_VRAM_TOTAL_BATCH_LIMIT = 2**19
LOW_VRAM_DEPTH_LIMIT = 8
LOW_VRAM_HEAD_DIM_LIMIT = 128
LOW_VRAM_ASPECT_RATIO_LIMIT = 64

FORBIDDEN_TOKENS = (
    "os.kill(",
    "signal.raise_signal(",
    "ctypes.",
    "subprocess.",
    "multiprocessing.",
    "socket.",
    "requests.",
)


def is_constrained_runtime() -> bool:
    """Return True for runtimes that should avoid aggressive architecture changes."""
    try:
        import torch
    except ImportError:
        return True

    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        total_memory_gb = props.total_memory / (1024**3)
        return total_memory_gb < 16

    return True


def validate_candidate_code(code: str, current_code: str = "") -> list[str]:
    """Return local-policy violations for a generated train.py candidate."""
    errors: list[str] = []

    if "MAX_SEQ_SIZE" in code:
        errors.append("use MAX_SEQ_LEN, not MAX_SEQ_SIZE")

    for token in FORBIDDEN_TOKENS:
        if token in code:
            errors.append(f"forbidden runtime token: {token}")

    baseline_compile_uses = current_code.count("torch.compile(") if current_code else 0
    if code.count("torch.compile(") > baseline_compile_uses:
        errors.append("do not add new torch.compile call sites")

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error: {exc.msg}"]

    if not is_constrained_runtime():
        return errors

    values = _extract_constant_assignments(tree)
    depth = values.get("DEPTH")
    aspect_ratio = values.get("ASPECT_RATIO")
    head_dim = values.get("HEAD_DIM")
    total_batch_size = values.get("TOTAL_BATCH_SIZE")

    if depth is not None and depth > LOW_VRAM_DEPTH_LIMIT:
        errors.append(f"DEPTH must stay <= {LOW_VRAM_DEPTH_LIMIT} on constrained nodes")
    if aspect_ratio is not None and aspect_ratio > LOW_VRAM_ASPECT_RATIO_LIMIT:
        errors.append(
            f"ASPECT_RATIO must stay <= {LOW_VRAM_ASPECT_RATIO_LIMIT} on constrained nodes"
        )
    if head_dim is not None and head_dim > LOW_VRAM_HEAD_DIM_LIMIT:
        errors.append(
            f"HEAD_DIM must stay <= {LOW_VRAM_HEAD_DIM_LIMIT} on constrained nodes"
        )
    if (
        depth is not None
        and aspect_ratio is not None
        and depth * aspect_ratio > LOW_VRAM_MODEL_DIM_LIMIT
    ):
        errors.append(
            f"DEPTH*ASPECT_RATIO must stay <= {LOW_VRAM_MODEL_DIM_LIMIT} on constrained nodes"
        )
    if total_batch_size is not None and total_batch_size > LOW_VRAM_TOTAL_BATCH_LIMIT:
        errors.append(
            "TOTAL_BATCH_SIZE must not exceed the baseline on constrained nodes"
        )

    return errors


def _extract_constant_assignments(tree: ast.AST) -> dict[str, int]:
    values: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    value = _const_int(node.value)
                    if value is not None:
                        values[target.id] = value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            value = _const_int(node.value)
            if value is not None:
                values[node.target.id] = value
    return values


def _const_int(node: ast.AST | None) -> int | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _const_int(node.operand)
        return -inner if inner is not None else None
    if isinstance(node, ast.BinOp):
        left = _const_int(node.left)
        right = _const_int(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Pow):
            return left**right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
    return None
