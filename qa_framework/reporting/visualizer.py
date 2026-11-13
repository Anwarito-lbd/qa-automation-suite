"""Generates publication-grade Test Pyramid PNG charts and standalone HTML reports."""

from __future__ import annotations

import html
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np

from qa_framework.reporting.collector import QASuiteSummary


def render_pyramid_chart(summary: QASuiteSummary, output_png: Path) -> None:
    """Render a 2-panel Test Pyramid & Per-Layer Latency PNG from real observed test runs."""
    output_png.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax_pyr, ax_lat) = plt.subplots(
        1,
        2,
        figsize=(13.5, 6.2),
        dpi=160,
        facecolor="#0b1120",
        gridspec_kw={"width_ratios": [1.05, 1.15]},
    )

    # --- Left Panel: Multi-Layer QA Test Pyramid ---
    ax_pyr.set_facecolor("#0b1120")
    ax_pyr.set_xlim(-1.32, 1.32)
    ax_pyr.set_ylim(-0.15, 3.25)
    ax_pyr.axis("off")

    layer_map = {layer.layer: layer for layer in summary.layers}
    tiers = [
        ("Layer 1: API & Property", "#2563eb", 0.0, 0.92, 1.24, 0.98),
        ("Layer 2: Web E2E (Playwright)", "#0ea5e9", 1.02, 1.94, 0.94, 0.68),
        ("Layer 3: Mobile (Appium/ADB)", "#10b981", 2.04, 2.96, 0.64, 0.36),
    ]

    for name, color, y0, y1, half_bot, half_top in tiers:
        poly = patches.Polygon(
            [(-half_bot, y0), (half_bot, y0), (half_top, y1), (-half_top, y1)],
            closed=True,
            facecolor=color,
            edgecolor="#e2e8f0",
            linewidth=1.5,
            alpha=0.88,
        )
        ax_pyr.add_patch(poly)
        info = layer_map.get(name)
        count_txt = (
            f"{info.passed}/{info.total} passed ({info.pass_rate_pct:.0f}%)" if info else "0/0"
        )
        ymid = (y0 + y1) / 2.0
        ax_pyr.text(
            0,
            ymid + 0.10,
            name,
            ha="center",
            va="center",
            color="#ffffff",
            fontsize=9.6,
            fontweight="bold",
        )
        ax_pyr.text(
            0,
            ymid - 0.16,
            count_txt,
            ha="center",
            va="center",
            color="#e2e8f0",
            fontsize=9.2,
        )

    ax_pyr.set_title(
        f"Multi-Layer QA Test Pyramid ({summary.passed}/{summary.total_tests} Passed)",
        color="#f8fafc",
        fontsize=12.5,
        fontweight="bold",
        pad=12,
    )

    # --- Right Panel: Observed Per-Layer Latency (p50 & p95 ms) ---
    ax_lat.set_facecolor("#111a2e")
    labels = [
        layer.layer.replace("Layer ", "L").replace(" (Playwright)", "").replace(" (Appium/ADB)", "")
        for layer in summary.layers
    ]
    p50_vals = [layer.p50_ms for layer in summary.layers]
    p95_vals = [layer.p95_ms for layer in summary.layers]
    y_pos = np.arange(len(labels))
    bar_h = 0.34

    bars_p50 = ax_lat.barh(
        y_pos + bar_h / 2, p50_vals, height=bar_h, color="#38bdf8", label="p50 Latency (ms)"
    )
    bars_p95 = ax_lat.barh(
        y_pos - bar_h / 2, p95_vals, height=bar_h, color="#f59e0b", label="p95 Latency (ms)"
    )

    ax_lat.set_yticks(y_pos)
    ax_lat.set_yticklabels(labels, color="#f1f5f9", fontsize=9.8, fontweight="bold")
    ax_lat.invert_yaxis()
    ax_lat.set_xlabel("Test Execution Duration (ms)", color="#cbd5e1", fontsize=10)
    ax_lat.tick_params(axis="x", colors="#cbd5e1")
    ax_lat.grid(axis="x", color="#253556", linestyle="--", alpha=0.6)
    for spine in ("top", "right"):
        ax_lat.spines[spine].set_visible(False)
    for spine in ("bottom", "left"):
        ax_lat.spines[spine].set_color("#334155")

    max_val = max(p95_vals + p50_vals + [10.0])
    ax_lat.set_xlim(0, max_val * 1.24)

    for bar in list(bars_p50) + list(bars_p95):
        width = bar.get_width()
        ax_lat.text(
            width + max_val * 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{width:.1f} ms",
            va="center",
            ha="left",
            color="#e2e8f0",
            fontsize=8.6,
        )

    ax_lat.legend(
        loc="lower right",
        facecolor="#0b1120",
        edgecolor="#334155",
        labelcolor="#f1f5f9",
        fontsize=9,
    )
    ax_lat.set_title(
        f"Per-Layer Latency Telemetry (Total Wall: {summary.wall_duration_s:.2f}s)",
        color="#f8fafc",
        fontsize=12.5,
        fontweight="bold",
        pad=12,
    )

    fig.suptitle(
        "AegisPay Multi-Layer QA Automation Suite — Verified Execution Telemetry",
        color="#93c5fd",
        fontsize=13.5,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(output_png, facecolor=fig.get_facecolor())
    plt.close(fig)


def render_html_report(summary: QASuiteSummary, output_html: Path) -> None:
    """Render a standalone HTML5 execution dashboard for the QA suite."""
    output_html.parent.mkdir(parents=True, exist_ok=True)

    layer_rows = "\n".join(
        f"""
        <tr>
          <td>{html.escape(layer.layer)}</td>
          <td>{layer.total}</td>
          <td>{layer.passed}</td>
          <td>{layer.failed}</td>
          <td>{layer.pass_rate_pct:.1f}%</td>
          <td>{layer.p50_ms:.2f} ms</td>
          <td>{layer.p95_ms:.2f} ms</td>
          <td>{layer.total_duration_ms:.2f} ms</td>
        </tr>
        """
        for layer in summary.layers
    )

    test_rows = "\n".join(
        f"""
        <tr>
          <td><code>{html.escape(t.nodeid)}</code></td>
          <td>{html.escape(t.layer)}</td>
          <td>{html.escape(t.sublayer)}</td>
          <td>
            <span class="pill pill-{html.escape(t.outcome)}">
              {html.escape(t.outcome.upper())}
            </span>
          </td>
          <td>{t.duration_ms:.2f} ms</td>
        </tr>
        """
        for t in summary.tests
    )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AegisPay QA Automation Report</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0b1120;
      color: #f1f5f9;
      margin: 0;
      padding: 24px;
    }}
    .wrap {{ max-width: 1120px; margin: 0 auto; }}
    h1, h2 {{ margin: 0 0 12px; }}
    .meta {{ color: #94a3b8; margin-bottom: 20px; font-size: 0.9rem; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }}
    .card {{
      background: #111a2e;
      border: 1px solid #253556;
      border-radius: 10px;
      padding: 16px;
    }}
    .card span {{ color: #94a3b8; font-size: 0.82rem; display: block; }}
    .card strong {{ font-size: 1.5rem; color: #10b981; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #111a2e;
      border: 1px solid #253556;
      border-radius: 10px;
      overflow: hidden;
      margin-bottom: 24px;
      font-size: 0.88rem;
    }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #253556; text-align: left; }}
    th {{ background: #17233d; color: #cbd5e1; font-size: 0.78rem; text-transform: uppercase; }}
    .pill {{ padding: 3px 8px; border-radius: 999px; font-size: 0.75rem; font-weight: 700; }}
    .pill-passed {{ background: rgba(16,185,129,0.2); color: #6ee7b7; }}
    .pill-failed, .pill-error {{ background: rgba(239,68,68,0.2); color: #fca5a5; }}
    .pill-skipped {{ background: rgba(245,158,11,0.2); color: #fcd34d; }}
    code {{ color: #93c5fd; font-size: 0.82rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>AegisPay Multi-Layer QA Execution Report</h1>
    <div class="meta">
      Generated UTC: {html.escape(summary.generated_at_utc)} |
      Wall Time: {summary.wall_duration_s:.3f}s
    </div>
    <div class="cards">
      <div class="card"><span>Total Tests</span><strong>{summary.total_tests}</strong></div>
      <div class="card"><span>Passed</span><strong>{summary.passed}</strong></div>
      <div class="card"><span>Pass Rate</span><strong>{summary.pass_rate_pct:.1f}%</strong></div>
      <div class="card"><span>Failed</span><strong>{summary.failed}</strong></div>
    </div>
    <h2>Layer Breakdown</h2>
    <table>
      <thead>
        <tr>
          <th>Layer</th><th>Total</th><th>Passed</th><th>Failed</th>
          <th>Pass Rate</th><th>p50</th><th>p95</th><th>Total</th>
        </tr>
      </thead>
      <tbody>{layer_rows}</tbody>
    </table>
    <h2>Test Cases ({summary.total_tests})</h2>
    <table>
      <thead>
        <tr><th>Node ID</th><th>Layer</th><th>Sub-Layer</th><th>Outcome</th><th>Duration</th></tr>
      </thead>
      <tbody>{test_rows}</tbody>
    </table>
  </div>
</body>
</html>
"""
    output_html.write_text(doc, encoding="utf-8")
