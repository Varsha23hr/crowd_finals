"""
detector.py

NOTE: this file is from the earlier live-multi-camera version of the app
and is no longer imported by app.py — the current app uses
video_processor.VideoJob instead, which analyzes one uploaded file at a
time. Kept here for reference / in case you want live-camera mode back.

CameraWorker: runs in its own thread, one per configured camera. Pulls
frames from the video source, runs YOLOv8 (+ optional ByteTrack tracking),
applies every enabled feature (zones, heatmap, optical flow, trend
prediction, privacy blur), draws the dashboard overlay, dispatches
email/SMS alerts with a cooldown, logs to CSV, and exposes the latest
annotated JPEG + stats dict for the Flask app to serve.
"""

import os
import math
import time
import threading
from collections import deque

import cv2
import numpy as np
from ultralytics import YOLO

import config
import zones as zones_mod
import heatmap as heatmap_mod
from optical_flow import OpticalFlowAnalyzer
from trend import TrendAnalyzer
from privacy import blur_faces_in_boxes
from utils.email_alert import send_alert_email
from utils.sms_alert import send_sms_alert
from utils.alert_logger import log_alert
from report_generator import generate_report


def get_status(count: int):
    if count >= config.CROWD_THRESHOLD:
        return "CRITICAL - OVERCROWDED", (0, 0, 255)
    if count >= config.SAFE_LIMIT:
        return "WARNING - BUSY", (0, 200, 255)
    return "SAFE", (0, 200, 0)


class CameraWorker(threading.Thread):
    def __init__(self, cam_id: str, name: str, source, shared_model: YOLO):
        super().__init__(daemon=True)
        self.cam_id = cam_id
        self.name = name
        self.source = source
        self.model = shared_model

        self._running = True
        self._lock = threading.Lock()
        self._latest_jpeg = None
        self._stats = {
            "camera": name, "count": 0, "status": "INITIALIZING", "fps": 0.0,
            "zones": [], "recommended_exit": None, "motion": 0.0,
            "motion_anomaly": False, "trend_warning": None,
        }

        self._flow_analyzer = OpticalFlowAnalyzer()
        self._trend_analyzer = TrendAnalyzer()
        self._count_history = deque(maxlen=5000)  # (timestamp_str, count) for the PDF report
        self._zones_peak = {}
        self._last_alert_time = {"overcrowd": 0.0, "motion": 0.0, "trend": 0.0}

    # -- public API used by app.py -----------------------------------------
    def get_jpeg(self):
        with self._lock:
            return self._latest_jpeg

    def get_stats(self):
        with self._lock:
            return dict(self._stats)

    def stop(self):
        self._running = False

    # -- alert dispatch helper ----------------------------------------------
    def _maybe_alert(self, kind: str, alert_type: str, zone: str, count: int,
                      threshold: int, details: dict):
        now = time.time()
        if now - self._last_alert_time.get(kind, 0) < config.ALERT_COOLDOWN_SECONDS:
            return
        self._last_alert_time[kind] = now

        timestamp = log_alert(self.name, alert_type, zone, count, threshold,
                               details=str(details))
        details_with_ts = {"Timestamp": timestamp, **details}
        send_alert_email(self.name, alert_type, details_with_ts)
        send_sms_alert(self.name, alert_type, details_with_ts)
        print(f"[ALERT][{self.name}] {alert_type} | zone={zone} count={count} "
              f"threshold={threshold} | {details}")

    # -- main loop ------------------------------------------------------------
    def run(self):
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            with self._lock:
                self._stats["status"] = "ERROR: cannot open source"
            print(f"[{self.name}] ERROR: could not open video source {self.source}")
            return

        zones_built = None
        prev_time = time.time()
        frame_id = 0

        while self._running:
            ret, frame = cap.read()
            if not ret:
                break
            frame_id += 1

            if config.PROCESS_WIDTH:
                h, w = frame.shape[:2]
                scale = config.PROCESS_WIDTH / w
                frame = cv2.resize(frame, (config.PROCESS_WIDTH, int(h * scale)))

            h, w = frame.shape[:2]
            if zones_built is None and config.ENABLE_ZONES:
                zones_built = zones_mod.build_zones(w, h)

            # --- Detection (+ optional tracking) ---
            if config.ENABLE_TRACKING:
                results = self.model.track(
                    frame, persist=True, tracker=config.TRACKER_CFG,
                    classes=[config.PERSON_CLASS_ID], conf=config.CONFIDENCE_THRESHOLD,
                    iou=getattr(config, "IOU_THRESHOLD", 0.7),
                    imgsz=config.PROCESS_WIDTH or 1920,
                    verbose=False,
                )[0]
            else:
                results = self.model.predict(
                    frame, classes=[config.PERSON_CLASS_ID],
                    conf=config.CONFIDENCE_THRESHOLD,
                    iou=getattr(config, "IOU_THRESHOLD", 0.7),
                    imgsz=config.PROCESS_WIDTH or 1920,
                    verbose=False,
                )[0]

            boxes = results.boxes
            person_count = len(boxes) if boxes is not None else 0

            centroids = []
            box_coords = []
            if boxes is not None:
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    box_coords.append((x1, y1, x2, y2))
                    centroids.append(((x1 + x2) // 2, (y1 + y2) // 2))

            status, color = get_status(person_count)

            # --- Privacy mode: blur faces before anything else touches the frame ---
            if config.ENABLE_PRIVACY_MODE:
                frame = blur_faces_in_boxes(frame, box_coords)

            # --- Heatmap overlay ---
            if config.ENABLE_HEATMAP and centroids:
                frame = heatmap_mod.compute_heatmap_overlay(frame, centroids)

            # --- Critical & Safe Distance Proximity Analysis ---
            crit_dist = getattr(config, "CRITICAL_DISTANCE", 55)
            n_det = len(box_coords)
            is_critical = [False] * n_det
            critical_pairs = []
            for i in range(n_det):
                c1 = centroids[i]
                for j in range(i + 1, n_det):
                    c2 = centroids[j]
                    dist = math.hypot(c1[0] - c2[0], c1[1] - c2[1])
                    if dist < crit_dist:
                        is_critical[i] = True
                        is_critical[j] = True
                        critical_pairs.append((c1, c2))

            COLOR_SAFE = (0, 220, 0)
            COLOR_CRITICAL = (0, 0, 255)

            # Draw connecting red lines between pairs violating critical distance
            for (c1, c2) in critical_pairs:
                cv2.line(frame, c1, c2, COLOR_CRITICAL, 1, cv2.LINE_AA)

            # --- Draw bounding boxes + track IDs ---
            if boxes is not None:
                for i, box in enumerate(boxes):
                    x1, y1, x2, y2 = box_coords[i]
                    box_color = COLOR_CRITICAL if (i < len(is_critical) and is_critical[i]) else COLOR_SAFE
                    cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
                    cv2.circle(frame, centroids[i], 3, box_color, -1)
                    label = ""
                    if config.ENABLE_TRACKING and box.id is not None:
                        label = f"ID {int(box.id[0])}"
                    if label:
                        cv2.putText(frame, label, (x1, max(0, y1 - 5)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, box_color, 1, cv2.LINE_AA)

            # --- Zones: assign counts, draw, get exit recommendation ---
            zone_stats = []
            recommended_exit = None
            if config.ENABLE_ZONES and zones_built is not None:
                zones_mod.assign_and_count(zones_built, centroids)
                recommended_exit = zones_mod.recommend_exit(zones_built)
                frame = zones_mod.draw_zones(frame, zones_built, recommended_exit)
                for z in zones_built:
                    zone_stats.append({"name": z["name"], "count": z["count"],
                                        "threshold": z["threshold"], "is_exit": z["is_exit"]})
                    self._zones_peak[z["name"]] = max(self._zones_peak.get(z["name"], 0), z["count"])

                    zstatus, _ = zones_mod.zone_status(z)
                    if zstatus == "CRITICAL":
                        self._maybe_alert(
                            f"zone_{z['name']}", "ZONE OVERCROWDED", z["name"], z["count"],
                            z["threshold"], {"Zone": z["name"], "Count": z["count"]},
                        )

            # --- Optical flow motion anomaly ---
            motion_mag, motion_anomaly = 0.0, False
            if config.ENABLE_OPTICAL_FLOW:
                motion_mag, motion_anomaly, _ = self._flow_analyzer.analyze(frame)
                frame = OpticalFlowAnalyzer.draw_motion_indicator(frame, motion_mag, motion_anomaly)
                if motion_anomaly:
                    self._maybe_alert(
                        "motion", "RAPID MOVEMENT / POSSIBLE STAMPEDE", "ALL", person_count,
                        config.CROWD_THRESHOLD, {"Motion magnitude": f"{motion_mag:.2f}"},
                    )

            # --- Trend-based early warning ---
            trend_warning = None
            if config.ENABLE_TREND_ALERTS:
                self._trend_analyzer.update(person_count)
                will_cross, eta, projected = self._trend_analyzer.predict()
                if will_cross:
                    trend_warning = f"Overcrowding predicted in ~{eta:.0f}s (projected {projected:.0f} people)"
                    self._maybe_alert(
                        "trend", "PREDICTED OVERCROWDING", "ALL", person_count,
                        config.CROWD_THRESHOLD,
                        {"ETA seconds": f"{eta:.0f}", "Projected count": f"{projected:.0f}"},
                    )

            # --- Global overcrowding alert ---
            if person_count >= config.CROWD_THRESHOLD:
                self._maybe_alert(
                    "overcrowd", "OVERCROWDING", "GLOBAL", person_count,
                    config.CROWD_THRESHOLD, {"Count": person_count},
                )

            # --- FPS + dashboard bar ---
            now = time.time()
            fps = 1.0 / max(now - prev_time, 1e-6)
            prev_time = now
            frame = self._draw_dashboard(frame, person_count, status, color, fps,
                                          recommended_exit, trend_warning)

            # --- Publish state for the Flask app ---
            self._count_history.append((time.strftime("%H:%M:%S"), person_count))
            ok, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            with self._lock:
                if ok:
                    self._latest_jpeg = jpeg.tobytes()
                self._stats.update({
                    "count": person_count, "status": status, "fps": round(fps, 1),
                    "zones": zone_stats,
                    "recommended_exit": {"name": recommended_exit[0], "count": recommended_exit[1]}
                    if recommended_exit else None,
                    "motion": round(motion_mag, 2), "motion_anomaly": motion_anomaly,
                    "trend_warning": trend_warning,
                })

        cap.release()
        with self._lock:
            self._stats["status"] = "STOPPED"

        if config.ENABLE_PDF_REPORT:
            from utils.alert_logger import read_recent_alerts
            alerts = [r for r in read_recent_alerts(limit=1000) if r.get("camera") == self.name]
            generate_report(self.name, list(self._count_history), alerts, self._zones_peak)

        print(f"[{self.name}] Worker stopped after {frame_id} frames.")

    # -- dashboard drawing ------------------------------------------------------
    def _draw_dashboard(self, frame, count, status, color, fps, recommended_exit, trend_warning):
        h, w = frame.shape[:2]
        bar_height = 75
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, bar_height), (30, 30, 30), -1)
        cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)

        cv2.putText(frame, f"{self.name}", (12, 18), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, f"People: {count}", (12, 42), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, f"Status: {status}", (170, 42), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, color, 2, cv2.LINE_AA)
        cv2.putText(frame, f"Threshold:{config.CROWD_THRESHOLD}  FPS:{fps:.1f}",
                    (12, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)

        if recommended_exit:
            cv2.putText(frame, f"Recommended exit: {recommended_exit[0]} ({recommended_exit[1]})",
                        (min(420, w - 260), 42), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (0, 255, 255), 1, cv2.LINE_AA)

        if trend_warning:
            cv2.putText(frame, trend_warning, (12, bar_height + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 2, cv2.LINE_AA)

        cv2.circle(frame, (w - 25, 25), 10, color, -1)
        return frame
