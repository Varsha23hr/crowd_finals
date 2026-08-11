"""
report_generator.py
Generates a one-file PDF session report at the end of a run: a summary page
(peak count, total alerts, duration, per-zone breakdown) plus a count-over-
time chart. Built with matplotlib's PdfPages so no extra PDF dependency is
needed beyond matplotlib.
"""

import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # headless backend, safe for server/background threads
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

import config


def generate_report(camera_name: str, count_history, alert_rows, zones_summary=None):
    """
    count_history: list of (timestamp_str, count) tuples collected during the run
    alert_rows: list of dicts (as returned by alert_logger.read_recent_alerts)
    zones_summary: optional dict {zone_name: peak_count}
    """
    os.makedirs(os.path.dirname(config.PDF_REPORT_PATH), exist_ok=True)

    counts = [c for _, c in count_history] or [0]
    peak = max(counts)
    avg = sum(counts) / len(counts)
    total_alerts = len(alert_rows)
    duration_samples = len(count_history)

    with PdfPages(config.PDF_REPORT_PATH) as pdf:
        # --- Page 1: summary ---
        fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
        ax.axis("off")
        lines = [
            "Crowd Detection & Overcrowding Alert System",
            "Session Report",
            "",
            f"Camera: {camera_name}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"Peak person count: {peak}",
            f"Average person count: {avg:.1f}",
            f"Configured threshold: {config.CROWD_THRESHOLD}",
            f"Total alert events: {total_alerts}",
            f"Samples recorded: {duration_samples}",
        ]
        if zones_summary:
            lines.append("")
            lines.append("Peak density by zone:")
            for zone, peak_count in zones_summary.items():
                lines.append(f"   - {zone}: {peak_count}")

        ax.text(0.05, 0.95, "\n".join(lines), va="top", ha="left", fontsize=12,
                family="monospace", transform=ax.transAxes)
        pdf.savefig(fig)
        plt.close(fig)

        # --- Page 2: count-over-time chart ---
        if count_history:
            fig, ax = plt.subplots(figsize=(8.27, 5))
            x = list(range(len(count_history)))
            y = [c for _, c in count_history]
            ax.plot(x, y, color="tab:blue", linewidth=1.5, label="Person count")
            ax.axhline(config.CROWD_THRESHOLD, color="red", linestyle="--",
                       label=f"Threshold ({config.CROWD_THRESHOLD})")
            ax.axhline(config.SAFE_LIMIT, color="orange", linestyle=":",
                       label=f"Safe limit ({config.SAFE_LIMIT})")
            ax.set_xlabel("Sample #")
            ax.set_ylabel("Person count")
            ax.set_title(f"Crowd density over time — {camera_name}")
            ax.legend(loc="upper left")
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

        # --- Page 3: alert log table ---
        if alert_rows:
            fig, ax = plt.subplots(figsize=(8.27, 11.69))
            ax.axis("off")
            table_data = [[r.get("timestamp", ""), r.get("alert_type", ""),
                           r.get("zone", ""), r.get("count", "")] for r in alert_rows[:30]]
            table = ax.table(
                cellText=table_data,
                colLabels=["Timestamp", "Type", "Zone", "Count"],
                loc="upper center",
                cellLoc="left",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(8)
            table.scale(1, 1.4)
            ax.set_title("Recent Alert Log", pad=20)
            pdf.savefig(fig)
            plt.close(fig)

    print(f"[REPORT] PDF session report saved to {config.PDF_REPORT_PATH}")
    return config.PDF_REPORT_PATH
