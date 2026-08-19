"""Minimal Prometheus text-format metrics.

Deliberately dependency-free: the edge server in a clinic runs the same code
on a mini-PC and should not need a metrics client library.
"""

from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(list)

BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 6, 10, 30)


def _key(name: str, labels: dict[str, str] | None):
    return name, tuple(sorted((labels or {}).items()))


def inc(name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
    with _lock:
        _counters[_key(name, labels)] += value


def observe(name: str, value: float, labels: dict[str, str] | None = None) -> None:
    with _lock:
        _histograms[_key(name, labels)].append(value)


def reset() -> None:
    with _lock:
        _counters.clear()
        _histograms.clear()


def _fmt_labels(labels: tuple[tuple[str, str], ...], extra: str = "") -> str:
    parts = [f'{k}="{v}"' for k, v in labels]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


def render() -> str:
    lines: list[str] = []
    with _lock:
        for (name, labels), value in sorted(_counters.items()):
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name}{_fmt_labels(labels)} {value}")
        for (name, labels), values in sorted(_histograms.items()):
            lines.append(f"# TYPE {name} histogram")
            ordered = sorted(values)
            for bucket in BUCKETS:
                count = sum(1 for v in ordered if v <= bucket)
                le = f'le="{bucket}"'
                lines.append(f"{name}_bucket{_fmt_labels(labels, le)} {count}")
            inf = 'le="+Inf"'
            lines.append(f"{name}_bucket{_fmt_labels(labels, inf)} {len(ordered)}")
            lines.append(f"{name}_sum{_fmt_labels(labels)} {sum(ordered)}")
            lines.append(f"{name}_count{_fmt_labels(labels)} {len(ordered)}")
    return "\n".join(lines) + "\n"
