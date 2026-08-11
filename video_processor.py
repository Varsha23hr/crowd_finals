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
                 model: YOLO, bytetrack: bool = True, uploaded_by: str = "Unknown",
                 threshold: int = config.CROWD_THRESHOLD):
        super().__init__(daemon=True)
        self.job_id = job_id
        self.filepath = filepath
        self.original_filename = original_filename
        self.model = model
        self.bytetrack = bytetrack
        self.uploaded_by = uploaded_by
        self.threshold = threshold
        self.high_limit = max(1, round(threshold * 0.8))
        self.safe_limit = max(1, round(threshold * 0.6))

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
        _ensure_dirs()

    # -- polled by /api/status/<job_id> --------------------------------
    def get_status(self):
        with self._lock:
            return dict(self._status)

    def _update(self, **kwargs):
        with self._lock:
            self._status.update(kwargs)

    def _classify(self, count):
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
                        imgsz=config.PROCESS_WIDTH or 1280,
                        verbose=False,
                    )[0]
                else:
                    results = self.model.predict(
                        frame, classes=[config.PERSON_CLASS_ID],
                        conf=config.CONFIDENCE_THRESHOLD,
                        imgsz=config.PROCESS_WIDTH or 1280,
                        verbose=False,
                    )[0]
                inference_ms = round((time.time() - infer_start) * 1000, 1)

                boxes = results.boxes
                person_count = len(boxes) if boxes is not None else 0
                box_coords = []
                centroids = []
                if boxes is not None:
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        box_coords.append((x1, y1, x2, y2))
                        centroids.append(((x1 + x2) // 2, (y1 + y2) // 2))
                self._last_boxes = box_coords
                self._last_count = person_count
                self._last_inference_ms = inference_ms
            else:
                # Reuse the last detection result to skip frames cheaply.
                box_coords = getattr(self, "_last_boxes", [])
                person_count = getattr(self, "_last_count", 0)
                inference_ms = getattr(self, "_last_inference_ms", 0.0)
                centroids = [((x1 + x2) // 2, (y1 + y2) // 2) for (x1, y1, x2, y2) in box_coords]

            status = self._classify(person_count)
            if person_count >= self.threshold:
                play_siren()
            else:
                stop_siren()
            counts_all.append(person_count)

            # --- accumulate heatmap grid ---
            h, w = frame.shape[:2]
            cols, rows = config.HEATMAP_GRID_COLS, config.HEATMAP_GRID_ROWS
            cell_w, cell_h = w / cols, h / rows
            for (cx, cy) in centroids:
                col = min(int(cx / cell_w), cols - 1)
                row = min(int(cy / cell_h), rows - 1)
                heatmap_grid[row, col] += 1

            # --- draw overlay ---
            color = STATUS_COLOR_BGR[status]
            for (x1, y1, x2, y2) in box_coords:
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            bar_h = 70
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (w, bar_h), (30, 30, 30), -1)
            cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)
            cv2.putText(frame, f"People: {person_count}", (14, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(frame, f"Status: {status}", (14, 54),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
            alert_text = "ALERT: OVERCROWDING" if status in ("HIGH", "CRITICAL") else "No active alert"
            cv2.putText(frame, alert_text, (min(260, w - 280), 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (68, 68, 239) if status in ("HIGH", "CRITICAL") else (200, 200, 200),
                        2, cv2.LINE_AA)
            ts_label = time.strftime("%H:%M:%S", time.gmtime(t_sec))
            cv2.putText(frame, ts_label, (w - 110, 54),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.circle(frame, (w - 20, 20), 9, color, -1)

            if writer is None:
                writer = cv2.VideoWriter(out_path, fourcc, fps, (w, h))
            writer.write(frame)
            last_good_frame = frame

            # --- per-frame data for live analysis panel ---
            density_pct_frame = min(100, round(100 * person_count / max(self.threshold, 1)))
            occupancy_pct_frame = min(100, round(100 * person_count / max(self.threshold * 1.5, 1)))
            frame_data_list.append({
                "frame": frame_id,
                "t": round(t_sec, 3),
                "count": person_count,
                "status": status,
                "density_pct": density_pct_frame,
                "occupancy_pct": occupancy_pct_frame,
                "threshold": self.threshold,
                "inference_ms": inference_ms,
            })

            # --- timeseries sampling ---
            if t_sec >= next_sample_t:
                timeseries.append({"t": round(t_sec, 1), "count": person_count, "status": status})
                next_sample_t += sample_interval

            # --- event tracking ---
            if status != "SAFE":
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
                if current_event is not None:
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
        if current_event is not None:
            self._close_event(current_event, events, keyframes)

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
                "-c:v", "libx264", "-preset", "fast",
                "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-an", h264_path,
            ], check=True, capture_output=True)
            os.replace(h264_path, out_path)
            print(f"[VideoJob {self.job_id}] Re-encoded to H.264 for browser playback.")
        except Exception as exc:
            print(f"[VideoJob {self.job_id}] H.264 re-encode skipped: {exc}")

        # Also re-encode the original upload if it's not browser-compatible
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            import subprocess
            # Probe: try a quick ffmpeg check on the uploaded file
            orig_h264 = self.filepath + ".h264.mp4"
            subprocess.run([
                ffmpeg_exe, "-y", "-i", self.filepath,
                "-c:v", "libx264", "-preset", "fast",
                "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-an", orig_h264,
            ], check=True, capture_output=True)
            os.replace(orig_h264, self.filepath)
            print(f"[VideoJob {self.job_id}] Original video re-encoded for browser playback.")
        except Exception as exc:
            print(f"[VideoJob {self.job_id}] Original re-encode skipped: {exc}")

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
        overall_risk = "CRITICAL" if severity_counts["CRITICAL"] else \
            "HIGH" if severity_counts["HIGH"] else \
            "WARNING" if severity_counts["WARNING"] else "SAFE"

        # derive the stored upload filename from the filepath
        uploaded_basename = os.path.basename(self.filepath)

        result = {
            "job_id": self.job_id,
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
                "avg_count": round(avg_count, 1),
                "max_count": max_count,
                "peak_time_sec": round(peak_time, 1),
                "total_alerts": len(events),
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

        self._update(status="done", progress=100)

    # -- helpers ------------------------------------------------------------
    def _close_event(self, ev, events, keyframes):
        duration = ev["end_t"] - ev["start_t"]
        if duration < config.MIN_EVENT_DURATION_SECONDS:
            return
        event_id = len(events) + 1
        kf_filename = f"{self.job_id}_kf{event_id}.jpg"
        kf_path = os.path.join(config.KEYFRAME_DIR, kf_filename)
        cv2.imwrite(kf_path, ev["keyframe_frame"])

        density_pct = min(100, round(100 * ev["peak_count"] / max(self.threshold, 1)))
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
                generate_report(result["original_filename"], count_history, alert_rows)
            finally:
                config.PDF_REPORT_PATH = original_path
        except Exception as exc:
            print(f"[VideoJob {self.job_id}] PDF generation skipped: {exc}")


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
