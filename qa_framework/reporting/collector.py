"""Parses pytest-json-report telemetry into structured multi-layer QA summaries."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class TestCaseTelemetry:
    nodeid: str
    layer: str
    sublayer: str
    outcome: str
    duration_ms: float


@dataclass(frozen=True)
class LayerSummary:
    layer: str
    total: int
    passed: int
    failed: int
    skipped: int
    pass_rate_pct: float
    total_duration_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True)
class QASuiteSummary:
    generated_at_utc: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    pass_rate_pct: float
    wall_duration_s: float
    layers: list[LayerSummary]
    tests: list[TestCaseTelemetry]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_nodeid(nodeid: str) -> tuple[str, str]:
    normalized = nodeid.replace("\\", "/")
    if "tests/api/test_properties.py" in normalized:
        return "Layer 1: API & Property", "Hypothesis Property/Stateful"
    if "tests/api/" in normalized:
        return "Layer 1: API & Property", "API Contract & RBAC"
    if "tests/web/" in normalized:
        return "Layer 2: Web E2E (Playwright)", "Headless Chromium"
    if "tests/mobile/" in normalized:
        return "Layer 3: Mobile (Appium/ADB)", "UIAutomator2 + ADB"
    return "Other", "Uncategorized"


def _compute_layer_summary(layer_name: str, items: list[TestCaseTelemetry]) -> LayerSummary:
    total = len(items)
    passed = sum(1 for t in items if t.outcome == "passed")
    failed = sum(1 for t in items if t.outcome in ("failed", "error"))
    skipped = sum(1 for t in items if t.outcome == "skipped")
    durations = [t.duration_ms for t in items]
    if durations:
        arr = np.array(durations, dtype=float)
        p50 = float(np.percentile(arr, 50))
        p95 = float(np.percentile(arr, 95))
        max_ms = float(np.max(arr))
        total_ms = float(np.sum(arr))
    else:
        p50 = p95 = max_ms = total_ms = 0.0

    pass_rate = (passed / total * 100.0) if total > 0 else 0.0
    return LayerSummary(
        layer=layer_name,
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        pass_rate_pct=round(pass_rate, 2),
        total_duration_ms=round(total_ms, 2),
        p50_ms=round(p50, 2),
        p95_ms=round(p95, 2),
        max_ms=round(max_ms, 2),
    )


def build_summary_from_pytest_json(raw_json_path: Path) -> QASuiteSummary:
    raw: dict[str, Any] = json.loads(raw_json_path.read_text(encoding="utf-8"))
    raw_tests = raw.get("tests", [])

    tests: list[TestCaseTelemetry] = []
    for entry in raw_tests:
        nodeid = str(entry.get("nodeid", ""))
        layer, sublayer = classify_nodeid(nodeid)
        outcome = str(entry.get("outcome", "unknown"))
        call_info = entry.get("call") or entry.get("setup") or {}
        duration_s = float(call_info.get("duration", 0.0))
        tests.append(
            TestCaseTelemetry(
                nodeid=nodeid,
                layer=layer,
                sublayer=sublayer,
                outcome=outcome,
                duration_ms=round(duration_s * 1000.0, 2),
            )
        )

    ordered_layers = [
        "Layer 1: API & Property",
        "Layer 2: Web E2E (Playwright)",
        "Layer 3: Mobile (Appium/ADB)",
    ]
    layer_summaries: list[LayerSummary] = []
    for lname in ordered_layers:
        subset = [t for t in tests if t.layer == lname]
        if subset:
            layer_summaries.append(_compute_layer_summary(lname, subset))

    extra = [t for t in tests if t.layer not in ordered_layers]
    if extra:
        layer_summaries.append(_compute_layer_summary("Other", extra))

    total = len(tests)
    passed = sum(1 for t in tests if t.outcome == "passed")
    failed = sum(1 for t in tests if t.outcome in ("failed", "error"))
    skipped = sum(1 for t in tests if t.outcome == "skipped")
    wall_s = float(raw.get("duration", 0.0))

    return QASuiteSummary(
        generated_at_utc=datetime.now(UTC).isoformat(),
        total_tests=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        pass_rate_pct=round((passed / total * 100.0) if total else 0.0, 2),
        wall_duration_s=round(wall_s, 3),
        layers=layer_summaries,
        tests=tests,
    )


def write_summary_json(summary: QASuiteSummary, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
