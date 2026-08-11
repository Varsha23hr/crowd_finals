"""
config.py — Central configuration for the full-featured Crowd Detection &
Overcrowding Alert System. Every feature can be switched on/off independently
via the FEATURE TOGGLES section, so you can demo them one at a time or all
together.
"""

# ---------------------------------------------------------------------------
# VIDEO / CAMERA SOURCES  (multi-camera support)
# ---------------------------------------------------------------------------
# Each entry becomes one tile on the web dashboard and runs in its own thread.
# "source" can be a video file path, an RTSP URL, or an integer (0) for a
# local webcam.
CAMERAS = [
    {"id": "cam1", "name": "Main Entrance", "source": "sample_videos/crowd_test.mp4"},
    # {"id": "cam2", "name": "Food Court", "source": "sample_videos/crowd_test2.mp4"},
]

PROCESS_WIDTH = 1920  # resize frames to this width for speed; None = keep original

# ---------------------------------------------------------------------------
# FEATURE TOGGLES — turn each add-on feature on/off
# ---------------------------------------------------------------------------
ENABLE_TRACKING = True            # persistent IDs via ByteTrack (model.track)
ENABLE_ZONES = False              # zone-based ROI thresholds + exit suggestion
                                   # (off by default — zone polygons assume a
                                   # fixed camera framing, not arbitrary uploads)
ENABLE_HEATMAP = True             # grid density heatmap overlay
ENABLE_OPTICAL_FLOW = True        # motion-energy stampede/anomaly precursor
ENABLE_TREND_ALERTS = True        # predictive "overcrowding in Xs" early warning
ENABLE_PRIVACY_MODE = False       # blur faces before display/recording
ENABLE_EMAIL_ALERTS = True
ENABLE_SMS_ALERTS = False         # requires Twilio credentials below
ENABLE_PDF_REPORT = True          # auto-generate session_report.pdf on stop

# ---------------------------------------------------------------------------
# YOLO MODEL
# ---------------------------------------------------------------------------
MODEL_PATH = "yolov8m.pt"
CONFIDENCE_THRESHOLD = 0.1
PERSON_CLASS_ID = 0
TRACKER_CFG = "bytetrack.yaml"   # bundled with ultralytics

# ---------------------------------------------------------------------------
# GLOBAL CROWD DENSITY THRESHOLDS (4-tier: SAFE / WARNING / HIGH / CRITICAL)
# ---------------------------------------------------------------------------
SAFE_LIMIT = 10        # count <  SAFE_LIMIT                    -> SAFE
HIGH_LIMIT = 15        # SAFE_LIMIT <= count < HIGH_LIMIT        -> WARNING
                        # HIGH_LIMIT <= count < CROWD_THRESHOLD  -> HIGH
CROWD_THRESHOLD = 20   # count >= CROWD_THRESHOLD                -> CRITICAL

# Minimum duration (seconds) a non-SAFE span must last to be logged as a
# distinct "overcrowding event" (filters out single-frame flicker).
MIN_EVENT_DURATION_SECONDS = 1.0

# ---------------------------------------------------------------------------
# VIDEO UPLOAD & OFFLINE PROCESSING
# ---------------------------------------------------------------------------
UPLOAD_DIR = "output/uploads"
PROCESSED_DIR = "output/processed"
KEYFRAME_DIR = "output/keyframes"
HEATMAP_DIR = "output/heatmaps"
ANALYSIS_DIR = "output/analyses"
REPORT_DIR = "output/reports"
HISTORY_FILE = "output/history.json"

ALLOWED_VIDEO_EXTENSIONS = {"mp4", "avi", "mov", "mkv"}
MAX_UPLOAD_MB = 500

# Run detection on every Nth frame to keep processing time reasonable on a
# demo/final-year-project machine; 1 = every frame (most accurate, slowest).
FRAME_SKIP = 1
# One timeseries sample per this many seconds of video (keeps result JSON small).
TIMESERIES_SAMPLE_SECONDS = 1.0

# ---------------------------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------------------------
# Demo credentials — CHANGE THESE before any real deployment. Passwords are
# stored as werkzeug password hashes, never in plaintext.
# Default login: admin / admin123
SECRET_KEY = "change-this-secret-key-before-deploying"
USERS = {
    "admin": "scrypt:32768:8:1$FMlyajXBxqtnNNTx$ae9e3361c9fccf7216de43b07b43846cffd19d2682768eade28170ce48e935e2ad2819725c1420370709b5d7532294ab562113ac95a740c3eb30777752fdbd3e",
}
SESSION_LIFETIME_HOURS = 12

# ---------------------------------------------------------------------------
# ZONES  (only used if ENABLE_ZONES = True)
# ---------------------------------------------------------------------------
# Polygon points are given in NORMALIZED coordinates (0.0-1.0 for both x and
# y) so the same zone definition works at any video resolution.
# "is_exit": True marks a zone as a possible evacuation exit; the system
# recommends whichever exit zone currently has the lowest density.
ZONES = [
    {
        "name": "Entrance",
        "polygon": [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)],
        "threshold": 12,
        "is_exit": False,
    },
    {
        "name": "Exit-A",
        "polygon": [(0.5, 0.0), (0.75, 0.0), (0.75, 1.0), (0.5, 1.0)],
        "threshold": 15,
        "is_exit": True,
    },
    {
        "name": "Exit-B",
        "polygon": [(0.75, 0.0), (1.0, 0.0), (1.0, 1.0), (0.75, 1.0)],
        "threshold": 15,
        "is_exit": True,
    },
]

# ---------------------------------------------------------------------------
# HEATMAP
# ---------------------------------------------------------------------------
HEATMAP_GRID_COLS = 12
HEATMAP_GRID_ROWS = 8
HEATMAP_ALPHA = 0.45  # blend strength of the heatmap overlay

# ---------------------------------------------------------------------------
# OPTICAL FLOW / MOTION ANOMALY (stampede precursor)
# ---------------------------------------------------------------------------
# Mean optical-flow magnitude above this value = "rapid coordinated movement"
FLOW_MAGNITUDE_THRESHOLD = 6.0
# Only compute optical flow every N frames (expensive) to keep FPS reasonable
FLOW_SAMPLE_EVERY_N_FRAMES = 2

# ---------------------------------------------------------------------------
# TREND-BASED EARLY WARNING
# ---------------------------------------------------------------------------
TREND_WINDOW_SECONDS = 10          # look-back window for the trend line
TREND_PREDICTION_SECONDS = 15      # how far ahead to project
TREND_MIN_SAMPLES = 5              # minimum samples before trusting the trend

# ---------------------------------------------------------------------------
# PRIVACY MODE
# ---------------------------------------------------------------------------
# Uses OpenCV's bundled Haar cascade — no internet/model download required.
FACE_BLUR_KERNEL = (35, 35)

# ---------------------------------------------------------------------------
# ALERTS — cooldown & logging
# ---------------------------------------------------------------------------
ALERT_COOLDOWN_SECONDS = 60
ALERT_LOG_PATH = "output/alert_log.csv"

# ---------------------------------------------------------------------------
# EMAIL (SMTP)
# ---------------------------------------------------------------------------
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = "varshavarshahr@gmail.com"
SENDER_PASSWORD = "rcje etwn fsdp pkjt"
RECEIVER_EMAIL = ["varshavarshahr@gmail.com"]


# ---------------------------------------------------------------------------
# PDF REPORT
# ---------------------------------------------------------------------------
PDF_REPORT_PATH = "output/session_report.pdf"

SQLALCHEMY_DATABASE_URI = "sqlite:///crowd_alert.db"
SQLALCHEMY_TRACK_MODIFICATIONS = False

# ---------------------------------------------------------------------------
# WEB DASHBOARD (Flask)
# ---------------------------------------------------------------------------
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 5000
STATS_POLL_INTERVAL_MS = 1000   # how often the browser polls /api/stats

# ---------------------------------------------------------------------------
# SIREN
# ---------------------------------------------------------------------------
SIREN_SOUND = "static/sounds/siren.mp3"