from __future__ import annotations


def read(path: str, default: str | None = None) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def read_int(path: str) -> int | None:
    v = read(path)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def input_of(label_path: str) -> str:
    """.../temp3_label -> .../temp3_input (only the file name is changed)."""
    return label_path[: -len("_label")] + "_input"
