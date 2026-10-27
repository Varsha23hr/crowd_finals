"""
video_processor.py

VideoJob: runs in its own thread, once per uploaded video. Reads the file
frame by frame, runs YOLOv8 (+ optional ByteTrack), draws the on-video
overlay (bounding boxes, count, density status, timestamp), accumulates a
crowd-density heatmap over the whole clip, detects overcrowding "events"
(contiguous spans above the SAFE tier) with keyframe snapshots, writes an
annotated output video, and — once finished — saves a single JSON results
file plus an entry in the history log that the dashboard reads.

This mirrors detector.CameraWorker's detection logic but is structured for
a finite, uploaded file rather than an infinite live stream.
"""

from sqlalchemy.engine import result
import json
import math
import os
import threading
import time
import uuid
from datetime import datetime

import cv2
import numpy as np
from ultralytics import YOLO

import config
from utils.alert_logger import log_alert
from utils.email_alert import send_alert_email
from utils.sms_alert import send_sms_alert
from utils.siren import play_siren, stop_siren

STATUS_ORDER = ["SAFE", "WARNING", "HIGH", "CRITICAL"]
STATUS_COLOR_BGR = {
    "SAFE": (34, 197, 94),       # #22C55E
    "WARNING": (21, 204, 250),   # #FACC15 (BGR)
    "HIGH": (35, 146, 251),      # #FB923C
    "CRITICAL": (68, 68, 239),   # #EF4444
}


def _ensure_dirs():
    for d in (config.UPLOAD_DIR, config.PROCESSED_DIR, config.KEYFRAME_DIR,
              config.HEATMAP_DIR, config.ANALYSIS_DIR, config.REPORT_DIR):
        os.makedirs(d, exist_ok=True)


class VideoJob(threading.Thread):
    """Processes one uploaded video end-to-end in a background thread."""

    def __init__(self, job_id: str, filepath: str, original_filename: str,
                 model: YOLO, bytetrack: bool = False, uploaded_by: str = "Unknown",
                 user_id: int = None, fallback_model: YOLO = None,
                 threshold: int = config.CROWD_THRESHOLD,
                 threshold_mode: str = "with"):
        super().__init__(daemon=True)
        self.job_id = job_id
        self.filepath = filepath
        self.original_filename = original_filename
        self.model = model
        self.fallback_model = fallback_model
        self._last_realtime_alert_t = -999  # cooldown tracker for real-time alerts
        self.bytetrack = bytetrack
        self.uploaded_by = uploaded_by
        self.user_id = user_id
        
        # Configure mode
        if threshold_mode == "without" or threshold in (0, None, "0", "without"):
            self.threshold_mode = "without"
            self.threshold = None
            self.high_limit = None
            self.safe_limit = None
        else:
            self.threshold_mode = "with"
            try:
                self.threshold = max(1, int(threshold))
            except (ValueError, TypeError):
                self.threshold = config.CROWD_THRESHOLD
            self.high_limit = max(1, round(self.threshold * 0.8))
            self.safe_limit = max(1, round(self.threshold * 0.6))

        self._lock = threading.Lock()
        self._status = {
            "job_id": job_id,
            "status": "queued",           # queued -> processing -> done | error
            "progress": 0,
            "frames_processed": 0,
            "total_frames": 0,
            "current_count": 0,
            "eta_seconds": None,
            "error": None,
        }
        self._preview_path = os.path.join(config.PROCESSED_DIR, f"{job_id}_preview.jpg")
        _ensure_dirs()

    # -- polled by /api/status/<job_id> --------------------------------
    def get_status(self):
        with self._lock:
            return dict(self._status)

    def _update(self, **kwargs):
        with self._lock:
            self._status.update(kwargs)

    def _classify(self, count):
        if self.threshold_mode == "without":
            return "MONITORING"
        if count >= self.threshold: return "CRITICAL"
        if count >= self.high_limit: return "HIGH"
        if count >= self.safe_limit: return "WARNING"
        return "SAFE"

    # -- main entry point -------------------------------------------------
    def run(self):
        try:
            self._process()
        except Exception as exc:  # keep the worker thread from dying silently
            self._update(status="error", error=str(exc))
            print(f"[VideoJob {self.job_id}] ERROR: {exc}")
            try:
                from app import app
                from models import db, UploadedVideo
                with app.app_context():
                    rec = UploadedVideo.query.filter_by(job_id=self.job_id).first()
                    if rec:
                        rec.status = "error"
                        db.session.commit()
            except Exception:
                pass

    def _process(self):
        self._update(status="processing")
        cap = cv2.VideoCapture(self.filepath)
        if not cap.isOpened():
            self._update(status="error", error="Could not open uploaded video file.")
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._update(total_frames=total_frames)

        out_path = os.path.join(config.PROCESSED_DIR, f"{self.job_id}.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = None  # created lazily once we know the (possibly resized) frame size

        heatmap_grid = np.zeros((config.HEATMAP_GRID_ROWS, config.HEATMAP_GRID_COLS), dtype=np.float64)
        last_good_frame = None

        timeseries = []
        events = []
        keyframes = []
        current_event = None
        counts_all = []
        frame_data_list = []  # per-frame data for live analysis panel
        peak_frame = None

        start_time = time.time()
        frame_id = 0
        next_sample_t = 0.0
        sample_interval = max(config.TIMESERIES_SAMPLE_SECONDS, 1.0 / fps)

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_id += 1

            if config.PROCESS_WIDTH:
                h, w = frame.shape[:2]
                scale = config.PROCESS_WIDTH / w
                frame = cv2.resize(frame, (config.PROCESS_WIDTH, int(h * scale)))

            t_sec = frame_id / fps

            run_detection = (frame_id % max(config.FRAME_SKIP, 1)) == 0
            inference_ms = 0.0
            if run_detection:
                infer_start = time.time()
                if self.bytetrack:
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
                body_boxes = []
                final_boxes = []  # list of (x1, y1, x2, y2, type) where type is 'body' or 'head'
                if boxes is not None:
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        body_boxes.append((x1, y1, x2, y2))
                        final_boxes.append((x1, y1, x2, y2, 'body'))

                # --- Fallback Head Detection (for heads whose body is not detected) ---
                if getattr(self, "fallback_model", None):
                    head_conf = getattr(config, "HEAD_CONFIDENCE_THRESHOLD", 0.25)
                    head_iou = getattr(config, "HEAD_IOU_THRESHOLD", 0.6)
                    results_fb = self.fallback_model.predict(
                        frame,
                        conf=head_conf,
                        iou=head_iou,
                        imgsz=config.PROCESS_WIDTH or 1920,
                        verbose=False,
                    )[0]
                    boxes_fb = results_fb.boxes
                    if boxes_fb is not None:
                        for box in boxes_fb:
                            fx1, fy1, fx2, fy2 = map(int, box.xyxy[0])
                            fcx, fcy = (fx1 + fx2) // 2, (fy1 + fy2) // 2
                            # Check if head center is inside any primary body box
                            is_inside = False
                            for (px1, py1, px2, py2) in body_boxes:
                                if px1 <= fcx <= px2 and py1 <= fcy <= py2:
                                    is_inside = True
                                    break
                            if not is_inside:
                                final_boxes.append((fx1, fy1, fx2, fy2, 'head'))

                box_coords = [(x1, y1, x2, y2) for (x1, y1, x2, y2, _) in final_boxes]
                centroids = [((x1 + x2) // 2, (y1 + y2) // 2) for (x1, y1, x2, y2, _) in final_boxes]
                person_count = len(final_boxes)

                # --- Critical & Safe Distance Proximity Analysis ---
                crit_dist = getattr(config, "CRITICAL_DISTANCE", 55)
                n_det = len(final_boxes)
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

                inference_ms = round((time.time() - infer_start) * 1000, 1)
                self._last_final_boxes = final_boxes
                self._last_box_coords = box_coords
                self._last_centroids = centroids
                self._last_is_critical = is_critical
                self._last_critical_pairs = critical_pairs
                self._last_count = person_count
                self._last_inference_ms = inference_ms
            else:
                # Reuse the last detection result to skip frames cheaply.
                final_boxes = getattr(self, "_last_final_boxes", [])
                box_coords = getattr(self, "_last_box_coords", [])
                centroids = getattr(self, "_last_centroids", [])
                is_critical = getattr(self, "_last_is_critical", [])
                critical_pairs = getattr(self, "_last_critical_pairs", [])
                person_count = getattr(self, "_last_count", 0)
                inference_ms = getattr(self, "_last_inference_ms", 0.0)

            counts_all.append(person_count)
            if peak_frame is None or (counts_all and person_count >= max(counts_all)):
                peak_frame = frame.copy()

            status = self._classify(person_count)
            if self.threshold_mode == "with" and person_count >= (self.threshold or 999999):
                play_siren()
            else:
                stop_siren()

            # --- Real-time email alert (only in With Threshold mode) ---
            ALERT_COOLDOWN_SECONDS = 60  # only send once per minute max
            if self.threshold_mode == "with" and status in ("HIGH", "CRITICAL"):
                if (t_sec - self._last_realtime_alert_t) >= ALERT_COOLDOWN_SECONDS:
                    self._last_realtime_alert_t = t_sec
                    try:
                        from app import app as flask_app
                        details = {
                            "Video": self.original_filename,
                            "Timestamp": f"{t_sec:.1f}s into video",
                            "Current crowd count": person_count,
                            "Threshold": self.threshold,
                            "Alert level": status,
                        }
                        send_alert_email(
                            self.original_filename,
                            f"REAL-TIME {status} CROWD ALERT at {t_sec:.1f}s",
                            details,
                            flask_app,
                        )
                        print(f"[VideoJob {self.job_id}] Real-time {status} alert sent at t={t_sec:.1f}s (count={person_count})")
                    except Exception as _e:
                        print(f"[VideoJob {self.job_id}] Real-time alert failed: {_e}")

            # --- accumulate heatmap grid ---
            h, w = frame.shape[:2]
            cols, rows = config.HEATMAP_GRID_COLS, config.HEATMAP_GRID_ROWS
            cell_w, cell_h = w / cols, h / rows
            for (cx, cy) in centroids:
                col = min(int(cx / cell_w), cols - 1)
                row = min(int(cy / cell_h), rows - 1)
                heatmap_grid[row, col] += 1

            # --- draw overlay: safe/critical bounding boxes, centroid dots, and red proximity lines ---
            COLOR_SAFE = (0, 220, 0)       # Green (BGR)
            COLOR_CRITICAL = (0, 0, 255)   # Red (BGR)

            # 1. Draw connecting red lines between pairs violating critical distance
            for (c1, c2) in critical_pairs:
                cv2.line(frame, c1, c2, COLOR_CRITICAL, 1, cv2.LINE_AA)

            # 2. Draw bounding boxes and centroid dots
            for i, (x1, y1, x2, y2, btype) in enumerate(final_boxes):
                box_color = COLOR_CRITICAL if (i < len(is_critical) and is_critical[i]) else COLOR_SAFE
                thickness = 1 if btype == 'head' else 2
                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, thickness)
                cv2.circle(frame, centroids[i], 3, box_color, -1)

            # 3. Clean status & timestamp overlay matching expected visual output
            if self.threshold_mode == "without":
                status_text = f"People: {person_count} | Mode: Without Threshold (Alerts Disabled)"
                status_color = (250, 180, 50)  # Bright cyan/sky blue
            else:
                status_text = f"Status: {status} | People: {person_count} / Limit: {self.threshold}"
                status_color = COLOR_CRITICAL if (status in ("HIGH", "CRITICAL") or any(is_critical)) else COLOR_SAFE
            cv2.putText(frame, status_text, (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, status_color, 2, cv2.LINE_AA)
            ts_label = time.strftime("%H:%M:%S", time.gmtime(t_sec))
            cv2.putText(frame, ts_label, (w - 110, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220, 220, 220), 1, cv2.LINE_AA)

            if writer is None:
                writer = cv2.VideoWriter(out_path, fourcc, fps, (w, h))
            writer.write(frame)
            last_good_frame = frame

            # Save latest annotated frame as JPEG for live preview
            if frame_id % max(config.FRAME_SKIP, 1) == 0:
                try:
                    cv2.imwrite(self._preview_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                except Exception:
                    pass

            # --- per-frame data for live analysis panel ---
            if self.threshold_mode == "without":
                density_pct_frame = min(100, round(person_count * 2.0))
                occupancy_pct_frame = "N/A"
                thresh_val = "Disabled"
            else:
                density_pct_frame = min(100, round(100 * person_count / max(self.threshold or 1, 1)))
                occupancy_pct_frame = min(100, round(100 * person_count / max((self.threshold or 1) * 1.5, 1)))
                thresh_val = self.threshold

            frame_data_list.append({
                "frame": frame_id,
                "t": round(t_sec, 3),
                "count": person_count,
                "status": status,
                "density_pct": density_pct_frame,
                "occupancy_pct": occupancy_pct_frame,
                "threshold": thresh_val,
                "inference_ms": inference_ms,
            })

            # --- timeseries sampling ---
            if t_sec >= next_sample_t:
                timeseries.append({"t": round(t_sec, 1), "count": person_count, "status": status, "density": density_pct_frame})
                next_sample_t += sample_interval

            # --- event tracking (only in With Threshold mode) ---
            if self.threshold_mode == "with" and status != "SAFE":
                if current_event is None:
                    current_event = {
                        "start_t": t_sec, "end_t": t_sec, "peak_count": person_count,
                        "severity": status, "keyframe_frame": frame.copy(),
                    }
                else:
                    current_event["end_t"] = t_sec
                    if STATUS_ORDER.index(status) > STATUS_ORDER.index(current_event["severity"]):
                        current_event["severity"] = status
                    if person_count >= current_event["peak_count"]:
                        current_event["peak_count"] = person_count
                        current_event["keyframe_frame"] = frame.copy()
            else:
                if current_event is not None and self.threshold_mode == "with":
                    self._close_event(current_event, events, keyframes)
                    current_event = None

            # --- progress reporting ---
            if frame_id % 5 == 0 or frame_id == total_frames:
                elapsed = time.time() - start_time
                pct = int(100 * frame_id / total_frames) if total_frames else 0
                rate = frame_id / elapsed if elapsed > 0 else 0
                remaining = (total_frames - frame_id) / rate if rate > 0 and total_frames else None
                self._update(
                    progress=min(pct, 99), frames_processed=frame_id,
                    current_count=person_count,
                    eta_seconds=round(remaining, 1) if remaining is not None else None,
                )

        # close any event still open at end of video
        if current_event is not None and self.threshold_mode == "with":
            self._close_event(current_event, events, keyframes)

        # In without-threshold mode, if no keyframes, capture peak crowd frame
        if self.threshold_mode == "without" and not keyframes and peak_frame is not None:
            kf_filename = f"{self.job_id}_kf1.jpg"
            kf_path = os.path.join(config.KEYFRAME_DIR, kf_filename)
            cv2.imwrite(kf_path, peak_frame)
            keyframes.append({
                "event_id": 1,
                "t": round(peak_time if 'peak_time' in locals() else 0.0, 1),
                "count": max(counts_all) if counts_all else 0,
                "severity": "MONITORING",
                "url": f"/media/keyframes/{kf_filename}",
            })

        cap.release()
        if writer is not None:
            writer.release()

        # Re-encode to H.264 for browser compatibility (mp4v is not supported
        # by HTML5 video elements). Uses ffmpeg bundled with imageio-ffmpeg.
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            import subprocess
            h264_path = out_path.replace(".mp4", "_h264.mp4")
            subprocess.run([
                ffmpeg_exe, "-y", "-i", out_path,
                "-c:v", "libx264", "-preset", "ultrafast",
                "-crf", "28", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-an", h264_path,
            ], check=True, capture_output=True)
            os.replace(h264_path, out_path)
            print(f"[VideoJob {self.job_id}] Re-encoded to H.264 for browser playback.")
        except Exception as exc:
            print(f"[VideoJob {self.job_id}] H.264 re-encode skipped: {exc}")



        duration_sec = frame_id / fps if fps else 0

        # --- final aggregate heatmap image ---
        heatmap_url = self._save_heatmap(heatmap_grid, last_good_frame)

        counts_all = counts_all or [0]
        max_count = max(counts_all)
        avg_count = sum(counts_all) / len(counts_all)
        peak_idx = counts_all.index(max_count)
        peak_time = peak_idx / fps if fps else 0

        severity_counts = {"WARNING": 0, "HIGH": 0, "CRITICAL": 0}
        for e in events:
            severity_counts[e["severity"]] = severity_counts.get(e["severity"], 0) + 1
        
        if self.threshold_mode == "without":
            overall_risk = "DISABLED"
        else:
            overall_risk = "CRITICAL" if severity_counts["CRITICAL"] else \
                "HIGH" if severity_counts["HIGH"] else \
                "WARNING" if severity_counts["WARNING"] else "SAFE"

        # derive the stored upload filename from the filepath
        uploaded_basename = os.path.basename(self.filepath)

        result = {
            "job_id": self.job_id,
            "user_id": self.user_id,
            "threshold_mode": self.threshold_mode,
            "original_filename": self.original_filename,
            "uploaded_by": self.uploaded_by,
            "processed_at": datetime.now().isoformat(timespec="seconds"),
            "video": {
                "duration_sec": round(duration_sec, 1),
                "fps": round(fps, 2),
                "resolution": f"{src_w}x{src_h}",
                "total_frames": frame_id,
                "processed_url": f"/media/processed/{self.job_id}.mp4",
                "uploaded_url": f"/media/uploads/{uploaded_basename}",
            },
            "summary": {
                "threshold_mode": self.threshold_mode,
                "avg_count": round(avg_count, 1),
                "max_count": max_count,
                "peak_time_sec": round(peak_time, 1),
                "total_alerts": len(events) if self.threshold_mode == "with" else 0,
                "alerts_by_severity": severity_counts,
                "overall_risk": overall_risk,
                "threshold": self.threshold,
                "high_limit": self.high_limit,
                "safe_limit": self.safe_limit,
            },
            "timeseries": timeseries,
            "events": events,
            "keyframes": keyframes,
            "heatmap_url": heatmap_url,
        }

        analysis_path = os.path.join(config.ANALYSIS_DIR, f"{self.job_id}.json")
        with open(analysis_path, "w") as f:
            json.dump(result, f)

        # write per-frame data for the live analysis panel
        frame_data_path = os.path.join(config.ANALYSIS_DIR, f"{self.job_id}_frames.json")
        with open(frame_data_path, "w") as f:
            json.dump({"fps": round(fps, 2), "total_frames": frame_id, "frames": frame_data_list}, f)

        self._append_history(result)
        self._dispatch_summary_alert(result)

        if config.ENABLE_PDF_REPORT:
            self._maybe_generate_pdf(result)

        # Update database record if exists
        try:
            from app import app
            from models import db, UploadedVideo
            with app.app_context():
                rec = UploadedVideo.query.filter_by(job_id=self.job_id).first()
                if rec:
                    rec.status = "done"
                    rec.max_count = result["summary"]["max_count"]
                    rec.avg_count = result["summary"]["avg_count"]
                    rec.total_alerts = result["summary"]["total_alerts"]
                    rec.overall_risk = result["summary"]["overall_risk"]
                    rec.duration_sec = result["video"]["duration_sec"]
                    rec.processed_at = datetime.utcnow()
                    db.session.commit()
        except Exception as db_err:
            print(f"[VideoJob] Warning updating DB record: {db_err}")

        # Clean up preview image
        try:
            if os.path.exists(self._preview_path):
                os.remove(self._preview_path)
        except Exception:
            pass

        self._update(status="done", progress=100)

    # -- helpers ------------------------------------------------------------
    def _close_event(self, ev, events, keyframes):
        if self.threshold_mode == "without" or self.threshold is None:
            return
        duration = ev["end_t"] - ev["start_t"]
        if duration < config.MIN_EVENT_DURATION_SECONDS:
            return
        event_id = len(events) + 1
        kf_filename = f"{self.job_id}_kf{event_id}.jpg"
        kf_path = os.path.join(config.KEYFRAME_DIR, kf_filename)
        cv2.imwrite(kf_path, ev["keyframe_frame"])

        density_pct = min(100, round(100 * ev["peak_count"] / max(self.threshold or 1, 1)))
        events.append({
            "id": event_id,
            "start_t": round(ev["start_t"], 1),
            "end_t": round(ev["end_t"], 1),
            "duration": round(duration, 1),
            "peak_count": ev["peak_count"],
            "density_pct": density_pct,
            "severity": ev["severity"],
            "status": "Resolved",
        })
        keyframes.append({
            "event_id": event_id,
            "t": round(ev["start_t"], 1),
            "count": ev["peak_count"],
            "severity": ev["severity"],
            "url": f"/media/keyframes/{kf_filename}",
        })

        log_alert(self.original_filename, f"{ev['severity']} OVERCROWDING", "GLOBAL",
                   ev["peak_count"], self.threshold,
                   details=f"duration={duration:.1f}s")

    def _save_heatmap(self, grid, base_frame):
        if base_frame is None:
            return None
        h, w = base_frame.shape[:2]
        if grid.max() > 0:
            norm = (grid / grid.max() * 255).astype(np.uint8)
        else:
            norm = grid.astype(np.uint8)
        heat_small = cv2.resize(norm, (w, h), interpolation=cv2.INTER_CUBIC)
        heat_small = cv2.GaussianBlur(heat_small, (0, 0), sigmaX=w / (config.HEATMAP_GRID_COLS * 2))
        heat_color = cv2.applyColorMap(heat_small, cv2.COLORMAP_JET)
        blended = cv2.addWeighted(heat_color, 0.6, base_frame, 0.4, 0)
        filename = f"{self.job_id}.jpg"
        path = os.path.join(config.HEATMAP_DIR, filename)
        cv2.imwrite(path, blended)
        return f"/media/heatmaps/{filename}"

    def _append_history(self, result):
        os.makedirs(os.path.dirname(config.HISTORY_FILE), exist_ok=True)
        history = []
        if os.path.exists(config.HISTORY_FILE):
            try:
                with open(config.HISTORY_FILE) as f:
                    history = json.load(f)
            except (json.JSONDecodeError, OSError):
                history = []
        history.insert(0, {
            "job_id": result["job_id"],
            "user_id": result.get("user_id"),
            "threshold_mode": result.get("threshold_mode", "with"),
            "threshold": result["summary"].get("threshold"),
            "original_filename": result["original_filename"],
            "uploaded_by": result["uploaded_by"],
            "processed_at": result["processed_at"],
            "status": "done",
            "max_count": result["summary"]["max_count"],
            "avg_count": result["summary"]["avg_count"],
            "total_alerts": result["summary"]["total_alerts"],
            "overall_risk": result["summary"]["overall_risk"],
            "duration_sec": result["video"]["duration_sec"],
        })
        with open(config.HISTORY_FILE, "w") as f:
            json.dump(history, f)

    def _dispatch_summary_alert(self, result):
        if result.get("threshold_mode") == "without" or result.get("summary", {}).get("threshold_mode") == "without":
            return
        severity = result["summary"]["overall_risk"]

        if severity not in ("HIGH", "CRITICAL"):
            return

        details = {
            "Video": result["original_filename"],
            "Max crowd count": result["summary"]["max_count"],
            "Total overcrowding events": result["summary"]["total_alerts"],
            "Overall risk": severity,
        }

        from app import app

        send_alert_email(
            result["original_filename"],
            f"{severity} OVERCROWDING DETECTED",
            details,
            app
        )

        send_sms_alert(
            result["original_filename"],
            f"{severity} OVERCROWDING DETECTED",
            details,
        )

    def _maybe_generate_pdf(self, result):
        try:
            from report_generator import generate_report
            count_history = [(f"{s['t']}s", s["count"]) for s in result["timeseries"]]
            alert_rows = [{"timestamp": f"{e['start_t']}s", "alert_type": e["severity"],
                           "zone": "GLOBAL", "count": e["peak_count"]} for e in result["events"]]
            report_path = os.path.join(config.REPORT_DIR, f"{self.job_id}.pdf")
            original_path = config.PDF_REPORT_PATH
            config.PDF_REPORT_PATH = report_path
            try:
                generate_report(result["original_filename"], count_history, alert_rows,
                                threshold=result["summary"].get("threshold"),
                                threshold_mode=result["summary"].get("threshold_mode", "with"))
            finally:
                config.PDF_REPORT_PATH = original_path
        except Exception as exc:
            print(f"[VideoJob {self.job_id}] PDF generation skipped: {exc}")


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
