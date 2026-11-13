"""Execute all 3 QA layers, collect telemetry, and render HTML/JSON/PNG proof."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from qa_framework.reporting.collector import build_summary_from_pytest_json, write_summary_json
from qa_framework.reporting.visualizer import render_html_report, render_pyramid_chart


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    raw_json = reports_dir / "pytest-raw.json"
    summary_json = reports_dir / "qa-summary.json"
    report_html = reports_dir / "qa-report.html"
    pyramid_png = root / "docs" / "images" / "qa-pyramid-report.png"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--json-report",
        f"--json-report-file={raw_json}",
    ]
    proc = subprocess.run(cmd, cwd=root, check=False)

    if not raw_json.exists():
        print("ERROR: pytest-json-report did not produce raw JSON telemetry.", file=sys.stderr)
        return proc.returncode or 1

    summary = build_summary_from_pytest_json(raw_json)
    write_summary_json(summary, summary_json)
    render_html_report(summary, report_html)
    render_pyramid_chart(summary, pyramid_png)

    print(
        f"\nQA Telemetry Generated: {summary.passed}/{summary.total_tests} passed "
        f"({summary.pass_rate_pct:.1f}%) in {summary.wall_duration_s:.2f}s"
    )
    print(f" - JSON:  {summary_json}")
    print(f" - HTML:  {report_html}")
    print(f" - Chart: {pyramid_png}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
