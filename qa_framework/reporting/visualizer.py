"""Generates publication-grade Test Pyramid PNG charts and interactive HTML QA workbench."""

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
        figsize=(14.0, 6.8),
        dpi=160,
        facecolor="#0d1117",
        gridspec_kw={"width_ratios": [1.05, 1.18]},
    )

    # --- Left Panel: Multi-Layer QA Test Pyramid ---
    ax_pyr.set_facecolor("#0d1117")
    ax_pyr.set_xlim(-1.45, 1.45)
    ax_pyr.set_ylim(-0.18, 4.25)
    ax_pyr.axis("off")

    layer_map = {layer.layer: layer for layer in summary.layers}
    tiers = [
        ("Layer 1: API & Property", "#2563eb", 0.0, 0.90, 1.36, 1.12),
        ("Layer 2: Web E2E", "#0ea5e9", 1.00, 1.90, 1.08, 0.84),
        ("Layer 3: Mobile QA", "#10b981", 2.00, 2.90, 0.80, 0.56),
        ("Layer 4: Unreal QA", "#8b5cf6", 3.00, 3.90, 0.52, 0.28),
    ]

    for name, color, y0, y1, half_bot, half_top in tiers:
        poly = patches.Polygon(
            [(-half_bot, y0), (half_bot, y0), (half_top, y1), (-half_top, y1)],
            closed=True,
            facecolor=color,
            edgecolor="#e6edf3",
            linewidth=1.4,
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
            ymid + 0.11,
            name,
            ha="center",
            va="center",
            color="#ffffff",
            fontsize=9.4,
            fontweight="bold",
        )
        ax_pyr.text(
            0,
            ymid - 0.14,
            count_txt,
            ha="center",
            va="center",
            color="#e6edf3",
            fontsize=8.6,
        )

    ax_pyr.set_title(
        f"4-Tier QA Test Pyramid ({summary.passed}/{summary.total_tests} Passed)",
        color="#e6edf3",
        fontsize=12.5,
        fontweight="bold",
        pad=12,
    )

    # --- Right Panel: Observed Per-Layer Latency (p50 & p95 ms) ---
    ax_lat.set_facecolor("#161b22")
    labels = [
        layer.layer.replace("Layer ", "L").replace(" (Playwright)", "") for layer in summary.layers
    ]
    p50_vals = [layer.p50_ms for layer in summary.layers]
    p95_vals = [layer.p95_ms for layer in summary.layers]
    y_pos = np.arange(len(labels))
    bar_h = 0.34

    bars_p50 = ax_lat.barh(
        y_pos + bar_h / 2, p50_vals, height=bar_h, color="#38bdf8", label="p50 Latency (ms)"
    )
    bars_p95 = ax_lat.barh(
        y_pos - bar_h / 2, p95_vals, height=bar_h, color="#d29922", label="p95 Latency (ms)"
    )

    ax_lat.set_yticks(y_pos)
    ax_lat.set_yticklabels(labels, color="#e6edf3", fontsize=9.6, fontweight="bold")
    ax_lat.invert_yaxis()
    ax_lat.set_xlabel("Test Execution Duration (ms)", color="#8b949e", fontsize=10)
    ax_lat.tick_params(axis="x", colors="#8b949e")
    ax_lat.grid(axis="x", color="#30363d", linestyle="--", alpha=0.7)
    for spine in ("top", "right"):
        ax_lat.spines[spine].set_visible(False)
    for spine in ("bottom", "left"):
        ax_lat.spines[spine].set_color("#30363d")

    max_val = max(p95_vals + p50_vals + [10.0])
    ax_lat.set_xlim(0, max_val * 1.26)

    for bar in list(bars_p50) + list(bars_p95):
        width = bar.get_width()
        ax_lat.text(
            width + max_val * 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{width:.1f} ms",
            va="center",
            ha="left",
            color="#e6edf3",
            fontsize=8.5,
        )

    ax_lat.legend(
        loc="lower right",
        facecolor="#0d1117",
        edgecolor="#30363d",
        labelcolor="#e6edf3",
        fontsize=9,
    )
    ax_lat.set_title(
        f"Per-Layer Latency Telemetry (Wall: {summary.wall_duration_s:.2f}s)",
        color="#e6edf3",
        fontsize=12.5,
        fontweight="bold",
        pad=12,
    )

    fig.suptitle(
        "AegisPay Multi-Layer QA Automation Suite — Verified Execution Telemetry",
        color="#58a6ff",
        fontsize=13.5,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(output_png, facecolor=fig.get_facecolor())
    plt.close(fig)


def render_html_report(summary: QASuiteSummary, output_html: Path) -> None:
    """Render an interactive precision HTML5 QA Telemetry & Triage Workbench."""
    output_html.parent.mkdir(parents=True, exist_ok=True)

    max_duration_ms = max((t.duration_ms for t in summary.tests), default=1.0) or 1.0
    layer_colors = {
        "Layer 1: API & Property": "#2563eb",
        "Layer 2: Web E2E": "#0ea5e9",
        "Layer 3: Mobile QA": "#10b981",
        "Layer 4: Unreal QA": "#8b5cf6",
    }

    dist_segments = "\n".join(
        f'<span class="dist-seg" title="{html.escape(layer.layer)}: {layer.total} tests" '
        f'style="width: {(layer.total / max(summary.total_tests, 1)) * 100:.1f}%; '
        f'background: {layer_colors.get(layer.layer, "#64748b")};"></span>'
        for layer in summary.layers
    )

    filter_buttons = "\n".join(
        f'<button type="button" class="filter-pill" data-layer="{html.escape(layer.layer)}">'
        f"{html.escape(layer.layer)} ({layer.total})</button>"
        for layer in summary.layers
    )

    layer_rows = "\n".join(
        f"""
        <tr>
          <td>
            <span class="layer-dot"
              style="background:{layer_colors.get(layer.layer, "#64748b")}"></span>
            {html.escape(layer.layer)}
          </td>
          <td class="num">{layer.total}</td>
          <td class="num">{layer.passed}</td>
          <td class="num">{layer.failed}</td>
          <td class="num">{layer.pass_rate_pct:.1f}%</td>
          <td class="num">{layer.p50_ms:.2f} ms</td>
          <td class="num">{layer.p95_ms:.2f} ms</td>
          <td class="num">{layer.total_duration_ms:.2f} ms</td>
        </tr>
        """
        for layer in summary.layers
    )

    test_rows = "\n".join(
        f"""
        <tr class="test-row" data-layer="{html.escape(t.layer)}"
            data-outcome="{html.escape(t.outcome)}">
          <td><code>{html.escape(t.nodeid)}</code></td>
          <td>{html.escape(t.layer)}</td>
          <td>{html.escape(t.sublayer)}</td>
          <td>
            <span class="pill pill-{html.escape(t.outcome)}">
              {html.escape(t.outcome.upper())}
            </span>
          </td>
          <td class="num">
            <div class="lat-cell">
              <span>{t.duration_ms:.2f} ms</span>
              <span class="lat-bar-bg">
                <span class="lat-bar-fill"
                  style="width:{min(100.0, (t.duration_ms / max_duration_ms) * 100):.1f}%">
                </span>
              </span>
            </div>
          </td>
        </tr>
        """
        for t in summary.tests
    )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AegisPay QA Telemetry Workbench</title>
  <style>
    :root {{
      --bg: #0d1117;
      --panel: #161b22;
      --panel-alt: #1c222b;
      --border: #30363d;
      --ink: #e6edf3;
      --muted: #8b949e;
      --pass: #2ea043;
      --warn: #d29922;
      --fail: #f85149;
      --accent: #58a6ff;
      --mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--ink);
      margin: 0;
      padding: 28px 20px 48px;
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1180px; margin: 0 auto; }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      flex-wrap: wrap;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 22px;
    }}
    h1 {{ margin: 0 0 4px; font-size: 1.45rem; letter-spacing: -0.01em; }}
    h2 {{ margin: 0 0 12px; font-size: 1.05rem; }}
    .meta {{ color: var(--muted); font-size: 0.86rem; font-family: var(--mono); }}
    .stack-tags {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .tag {{
      padding: 4px 10px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--panel);
      font-size: 0.76rem;
      color: #c9d1d9;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px 18px;
    }}
    .card span {{ color: var(--muted); font-size: 0.82rem; display: block; margin-bottom: 4px; }}
    .card strong {{
      font-family: var(--mono);
      font-variant-numeric: tabular-nums;
      font-size: 1.65rem;
      color: #3fb950;
    }}
    .card strong.warn {{ color: var(--warn); }}
    .dist-bar {{
      display: flex;
      height: 10px;
      width: 100%;
      border-radius: 999px;
      overflow: hidden;
      background: var(--panel);
      border: 1px solid var(--border);
      margin-bottom: 24px;
    }}
    .dist-seg {{ height: 100%; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
      margin-bottom: 24px;
    }}
    .toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      background: var(--panel-alt);
    }}
    .filter-group {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .filter-pill {{
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--muted);
      padding: 6px 11px;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
    }}
    .filter-pill.active {{
      background: #1f6feb;
      border-color: #388bfd;
      color: #ffffff;
    }}
    .search-box {{
      background: var(--bg);
      border: 1px solid var(--border);
      color: var(--ink);
      padding: 7px 12px;
      border-radius: 7px;
      font-size: 0.85rem;
      min-width: 240px;
    }}
    .table-wrap {{ width: 100%; overflow-x: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
    }}
    th, td {{
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      background: var(--panel-alt);
      color: var(--muted);
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    td.num, th.num {{
      text-align: right;
      font-family: var(--mono);
      font-variant-numeric: tabular-nums;
    }}
    .layer-dot {{
      display: inline-block;
      width: 9px;
      height: 9px;
      border-radius: 999px;
      margin-right: 7px;
    }}
    .lat-cell {{ display: inline-flex; align-items: center; gap: 10px; }}
    .lat-bar-bg {{
      width: 72px;
      height: 6px;
      border-radius: 999px;
      background: var(--bg);
      overflow: hidden;
      display: inline-block;
    }}
    .lat-bar-fill {{ height: 100%; background: var(--accent); display: block; }}
    .pill {{
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 0.73rem;
      font-weight: 700;
    }}
    .pill-passed {{ background: rgba(46,160,67,0.2); color: #56d364; }}
    .pill-failed, .pill-error {{ background: rgba(248,81,73,0.2); color: #ff7b72; }}
    .pill-skipped {{ background: rgba(210,153,34,0.2); color: #e3b341; }}
    code {{ color: #79c0ff; font-family: var(--mono); font-size: 0.81rem; }}
    .hidden-row {{ display: none; }}
    @media (max-width: 780px) {{
      .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="header">
      <div>
        <h1>AegisPay QA Telemetry Workbench</h1>
        <div class="meta">
          UTC: {html.escape(summary.generated_at_utc)} | Wall Time: {summary.wall_duration_s:.3f}s
        </div>
      </div>
      <div class="stack-tags">
        <span class="tag">Pytest + Hypothesis</span>
        <span class="tag">Playwright + Selenium</span>
        <span class="tag">Appium + ADB + Kotlin</span>
        <span class="tag">UE5 Gauntlet</span>
        <span class="tag">JIRA REST v3</span>
      </div>
    </header>

    <div class="cards">
      <div class="card"><span>Total Executed</span><strong>{summary.total_tests}</strong></div>
      <div class="card"><span>Passed</span><strong>{summary.passed}</strong></div>
      <div class="card"><span>Pass Rate</span><strong>{summary.pass_rate_pct:.1f}%</strong></div>
      <div class="card">
        <span>Wall Duration</span><strong class="warn">{summary.wall_duration_s:.2f}s</strong>
      </div>
    </div>

    <div class="dist-bar" title="Test distribution across QA layers">{dist_segments}</div>

    <h2>Layer Telemetry Breakdown</h2>
    <div class="panel">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Layer</th><th class="num">Total</th><th class="num">Passed</th>
              <th class="num">Failed</th><th class="num">Pass Rate</th>
              <th class="num">p50</th><th class="num">p95</th><th class="num">Sum</th>
            </tr>
          </thead>
          <tbody>{layer_rows}</tbody>
        </table>
      </div>
    </div>

    <h2>Executed Test Cases (<span id="visible-count">{summary.total_tests}</span>)</h2>
    <div class="panel">
      <div class="toolbar">
        <div class="filter-group" role="group" aria-label="Filter by QA layer">
          <button type="button" class="filter-pill active" data-layer="ALL">
            All ({summary.total_tests})
          </button>
          {filter_buttons}
        </div>
        <input id="test-search" type="search" class="search-box"
               placeholder="Filter by test node ID..." aria-label="Filter tests by node ID" />
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Node ID</th><th>Layer</th><th>Sub-Layer</th>
              <th>Outcome</th><th class="num">Duration</th>
            </tr>
          </thead>
          <tbody>{test_rows}</tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    (() => {{
      let activeLayer = "ALL";
      const pills = Array.from(document.querySelectorAll(".filter-pill"));
      const rows = Array.from(document.querySelectorAll(".test-row"));
      const searchInput = document.getElementById("test-search");
      const visibleCount = document.getElementById("visible-count");

      function applyFilters() {{
        const query = (searchInput.value || "").trim().toLowerCase();
        let shown = 0;
        for (const row of rows) {{
          const layerMatch = activeLayer === "ALL" || row.dataset.layer === activeLayer;
          const textMatch = !query || row.textContent.toLowerCase().includes(query);
          const visible = layerMatch && textMatch;
          row.classList.toggle("hidden-row", !visible);
          if (visible) shown += 1;
        }}
        visibleCount.textContent = String(shown);
      }}

      for (const pill of pills) {{
        pill.addEventListener("click", () => {{
          activeLayer = pill.dataset.layer || "ALL";
          pills.forEach(p => p.classList.toggle("active", p === pill));
          applyFilters();
        }});
      }}
      searchInput.addEventListener("input", applyFilters);
    }})();
  </script>
</body>
</html>
"""
    output_html.write_text(doc, encoding="utf-8")
