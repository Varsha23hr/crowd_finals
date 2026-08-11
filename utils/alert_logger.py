"""
utils/alert_logger.py
Appends every alert event (overcrowding, zone breach, motion anomaly,
trend warning) to a single CSV audit trail.
"""

import csv
import os
import threading
from datetime import datetime

import config

_lock = threading.Lock()


def init_log_file() -> None:
    os.makedirs(os.path.dirname(config.ALERT_LOG_PATH), exist_ok=True)
    if not os.path.exists(config.ALERT_LOG_PATH):
        with open(config.ALERT_LOG_PATH, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["timestamp", "camera", "alert_type", "zone", "count", "threshold", "details"]
            )


def log_alert(camera_name: str, alert_type: str, zone: str, count: int,
              threshold: int, details: str = "") -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        with open(config.ALERT_LOG_PATH, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, camera_name, alert_type, zone, count, threshold, details])
    return timestamp


def read_recent_alerts(limit: int = 20):
    """Returns the most recent `limit` alert rows (newest first) for the dashboard."""
    if not os.path.exists(config.ALERT_LOG_PATH):
        return []
    with _lock:
        with open(config.ALERT_LOG_PATH, mode="r", newline="") as f:
            rows = list(csv.DictReader(f))
    return list(reversed(rows))[:limit]
