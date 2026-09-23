"""In-process metrics with a Prometheus text exposition. Pure; no dependencies.

Counters and summaries (count / sum / max) keyed by small label sets. Values are per
process; a multi-worker deployment scrapes each worker. Nothing here ever holds content,
identifiers of users or analyses, or anything a label could leak: labels are routes,
methods, statuses, step names, provider names and operations only.
"""

import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

Labels = tuple[tuple[str, str], ...]


def _labels(values: Mapping[str, str]) -> Labels:
    return tuple(sorted((k, str(v)) for k, v in values.items()))


def _fmt_labels(labels: Labels) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
    return "{" + inner + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclass
class Counter:
    name: str
    help: str
    _values: dict[Labels, float] = field(default_factory=dict)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = _labels(labels)
        self._values[key] = self._values.get(key, 0.0) + amount

    def get(self, **labels: str) -> float:
        return self._values.get(_labels(labels), 0.0)

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} counter"
        for key, value in sorted(self._values.items()):
            yield f"{self.name}{_fmt_labels(key)} {_num(value)}"


@dataclass
class _Stat:
    count: int = 0
    total: float = 0.0
    maximum: float = 0.0


@dataclass
class Summary:
    """count / sum / max of an observation, e.g. a latency in seconds."""

    name: str
    help: str
    _values: dict[Labels, _Stat] = field(default_factory=dict)

    def observe(self, value: float, **labels: str) -> None:
        stat = self._values.setdefault(_labels(labels), _Stat())
        stat.count += 1
        stat.total += value
        stat.maximum = max(stat.maximum, value)

    def get(self, **labels: str) -> _Stat:
        return self._values.get(_labels(labels), _Stat())

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} summary"
        for key, stat in sorted(self._values.items()):
            labels = _fmt_labels(key)
            yield f"{self.name}_count{labels} {stat.count}"
            yield f"{self.name}_sum{labels} {_num(stat.total)}"
            yield f"{self.name}_max{labels} {_num(stat.maximum)}"


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.6f}"


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._setup()

    def _setup(self) -> None:
        self._started = time.monotonic()
        self.http_requests = Counter("verixa_http_requests_total", "HTTP requests by route/status.")
        self.http_latency = Summary(
            "verixa_http_request_duration_seconds", "HTTP request latency by route."
        )
        self.pipeline_steps = Counter(
            "verixa_pipeline_steps_total", "Pipeline step outcomes by step and status."
        )
        self.step_latency = Summary(
            "verixa_pipeline_step_duration_seconds", "Pipeline step duration by step."
        )
        self.analyses = Counter(
            "verixa_analyses_total", "Analyses finished by type and final status."
        )
        self.provider_calls = Counter(
            "verixa_provider_calls_total", "Provider calls by provider, operation and status."
        )
        self.provider_latency = Summary(
            "verixa_provider_call_duration_seconds", "Provider call latency by provider/operation."
        )

    # -- recording (each call is a tiny critical section) -------------------------------------

    def record_http(self, *, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self.http_requests.inc(method=method, route=route, status=str(status))
            self.http_latency.observe(seconds, method=method, route=route)

    def record_step(self, *, step: str, status: str, seconds: float) -> None:
        with self._lock:
            self.pipeline_steps.inc(step=step, status=status)
            self.step_latency.observe(seconds, step=step)

    def record_analysis(self, *, type: str, status: str) -> None:
        with self._lock:
            self.analyses.inc(type=type, status=status)

    def record_provider_call(
        self, *, provider: str, operation: str, status: str, seconds: float | None
    ) -> None:
        with self._lock:
            self.provider_calls.inc(provider=provider, operation=operation, status=status)
            if seconds is not None:
                self.provider_latency.observe(seconds, provider=provider, operation=operation)

    # -- exposition -----------------------------------------------------------------------------

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._started

    def render(self) -> str:
        with self._lock:
            lines: list[str] = [
                "# HELP verixa_uptime_seconds Seconds since this process started.",
                "# TYPE verixa_uptime_seconds gauge",
                f"verixa_uptime_seconds {self.uptime_seconds:.3f}",
            ]
            for metric in (
                self.http_requests,
                self.http_latency,
                self.pipeline_steps,
                self.step_latency,
                self.analyses,
                self.provider_calls,
                self.provider_latency,
            ):
                lines.extend(metric.render())
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Tests only."""
        with self._lock:
            self._setup()


registry = MetricsRegistry()
