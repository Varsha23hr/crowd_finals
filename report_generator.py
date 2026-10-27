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


def generate_report(camera_name: str, count_history, alert_rows, zones_summary=None, threshold=None, threshold_mode="with"):
    """
    count_history: list of (timestamp_str, count) tuples collected during the run
    alert_rows: list of dicts (as returned by alert_logger.read_recent_alerts)
    zones_summary: optional dict {zone_name: peak_count}
    threshold: user-configured safe crowd threshold (or None if without threshold)
    threshold_mode: "with" or "without"
    """
    os.makedirs(os.path.dirname(config.PDF_REPORT_PATH), exist_ok=True)

    counts = [c for _, c in count_history] or [0]
    peak = max(counts)
    avg = sum(counts) / len(counts)
    total_alerts = len(alert_rows) if threshold_mode == "with" else 0
    duration_samples = len(count_history)

    is_without = (threshold_mode == "without" or threshold in (None, 0, "Disabled"))
    mode_label = "Without Threshold (Alerts Disabled)" if is_without else "With Threshold"
    thresh_display = "Disabled (Monitoring Mode)" if is_without else f"{threshold or config.CROWD_THRESHOLD} people"

    with PdfPages(config.PDF_REPORT_PATH) as pdf:
        # --- Page 1: summary ---
        fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
        ax.axis("off")
        lines = [
            "Crowd Detection & Overcrowding Alert System",
            "Session Report",
            "",
            f"Video / Camera: {camera_name}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Analysis Mode: {mode_label}",
            f"Safe Threshold: {thresh_display}",
            "",
            f"Peak person count: {peak}",
            f"Average person count: {avg:.1f}",
            f"Total alert events: {total_alerts if not is_without else '0 (Threshold alerts disabled)'}",
            f"Samples recorded: {duration_samples}",
        ]
        if zones_summary:
            lines.append("")
            lines.append("Peak density by zone:")
            for zone, peak_count in zones_summary.items():
                lines.append(f"   - {zone}: {peak_count}")

        if is_without:
            lines.append("")
            lines.append("[NOTE] This session was processed in Without Threshold mode.")
            lines.append("       People count and density were monitored continuously;")
            lines.append("       capacity threshold alerts and alarms were disabled.")

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
            if not is_without:
                effective_threshold = int(threshold) if threshold else config.CROWD_THRESHOLD
                safe_limit = max(1, round(effective_threshold * 0.6))
                ax.axhline(effective_threshold, color="red", linestyle="--",
                           label=f"Threshold ({effective_threshold})")
                ax.axhline(safe_limit, color="orange", linestyle=":",
                           label=f"Safe limit ({safe_limit})")
            else:
                ax.set_title(f"Crowd Count Over Time (Monitoring Mode — Alerts Disabled) — {camera_name}")
            if not is_without:
                ax.set_title(f"Crowd Density Over Time — {camera_name}")
            ax.set_xlabel("Sample #")
            ax.set_ylabel("Person count")
            ax.legend(loc="upper left")
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

        # --- Page 3: alert log table ---
        if alert_rows and not is_without:
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
        elif is_without:
            fig, ax = plt.subplots(figsize=(8.27, 11.69))
            ax.axis("off")
            ax.text(0.5, 0.5, "Threshold-based alerts were disabled for this video analysis.\nContinuous people counting and density monitoring performed successfully.",
                    va="center", ha="center", fontsize=13, family="sans-serif", color="#475569")
            ax.set_title("Alert Log Status", pad=20)
            pdf.savefig(fig)
            plt.close(fig)

    print(f"[REPORT] PDF session report saved to {config.PDF_REPORT_PATH}")
    return config.PDF_REPORT_PATH
