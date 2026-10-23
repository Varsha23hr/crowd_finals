HEAD
# Crowd Detection & Overcrowding Analysis System

An authenticated web dashboard that analyzes **uploaded videos** (not live
CCTV) with YOLOv8 to detect people, estimate crowd density, flag
overcrowding events, and generate exportable analytical reports.

This is the upload-and-analyze version of the project. The earlier
live-multi-camera mode (`CameraWorker` in `detector.py`) is kept in the repo
for reference but is no longer wired into `app.py`.

## What it does
1. **Sign in** on the login page (session-based auth).
2. **Upload a video** (MP4 / AVI / MOV / MKV) via drag-and-drop or the file
   picker.
3. The video is analyzed in the background: YOLOv8 detects people frame by
   frame, a 4-tier density status (Safe / Warning / High / Critical) is
   computed, overcrowding **events** are logged with start/end time, peak
   count and severity, **keyframe snapshots** are captured automatically,
   and a **density heatmap** is built for the whole clip.
4. Review results on the **Analysis** page: the annotated video (boxes,
   count, status and timestamp are burned into the frames), summary panel,
   five analytics charts, a clickable event timeline, the events table, the
   heatmap, and the keyframe gallery.
5. Export a **PDF / Excel / CSV** report from the **Reports** page, or
   browse everything you've ever analyzed on the **History** page.

## Project structure
```
crowd_alert_v2/
├── app.py                # Flask entry point — run this
├── auth.py                # session login/logout + @login_required
├── video_processor.py     # VideoJob: the upload → analysis pipeline
├── config.py              # ALL settings, thresholds, auth, feature toggles
├── report_generator.py    # matplotlib PdfPages report (used per-video now)
├── heatmap.py, zones.py, optical_flow.py, trend.py, privacy.py, detector.py
│                          # legacy live-camera modules, kept for reference
├── utils/
│   ├── email_alert.py
│   ├── sms_alert.py       # Twilio
│   └── alert_logger.py    # CSV audit trail
├── templates/
│   ├── login.html
│   └── dashboard.html     # Dashboard / Upload / Analysis / Reports / History / Settings
├── static/
│   ├── style.css
│   └── app.js
├── output/
│   ├── uploads/            # raw uploaded videos
│   ├── processed/          # annotated output videos served to the player
│   ├── keyframes/          # overcrowding-event snapshots
│   ├── heatmaps/           # per-video density heatmap images
│   ├── analyses/           # one JSON per analyzed video (the API's source of truth)
│   ├── reports/            # generated PDF reports
│   └── history.json        # rolling list of every analyzed video, powers History + Dashboard
└── requirements.txt
```

## 1. Install
```bash
pip install -r requirements.txt
```
`yolov8n.pt` auto-downloads on first run (needs internet once, then cached).
`bytetrack.yaml` ships inside the `ultralytics` package.

## 2. Configure — `config.py`
- **`SAFE_LIMIT` / `HIGH_LIMIT` / `CROWD_THRESHOLD`** — the 4-tier density
  thresholds: `< SAFE_LIMIT` = Safe, up to `HIGH_LIMIT` = Warning, up to
  `CROWD_THRESHOLD` = High, at/above = Critical.
- **`USERS`** — demo login is `admin` / `admin123`. Add more users with
  `werkzeug.security.generate_password_hash("your-password")`, and change
  `SECRET_KEY` before deploying anywhere real.
- **`FRAME_SKIP`** — run detection every Nth frame to speed up long videos.
- **`MAX_UPLOAD_MB`** — upload size limit (default 500MB).
- **Feature toggles** (`ENABLE_*`) — tracking, heatmap, optical-flow motion
  anomaly, trend-based early warning, privacy face-blur, email/SMS alerts,
  auto PDF report. Zones (`ENABLE_ZONES`) are off by default since zone
  polygons assume one fixed camera framing, not arbitrary uploads.
- **Email / SMS** — same as before (`SENDER_EMAIL`/`SENDER_PASSWORD`/
  `RECEIVER_EMAIL`, Twilio credentials). A summary alert fires automatically
  when a video's overall risk comes back High or Critical.

## 3. Run
```bash
python app.py
```
Open **http://localhost:5000**, sign in, and upload a video.

## API reference (used by the dashboard's own JS — handy for integration)
| Endpoint | Method | Purpose |
|---|---|---|
| `/login` | GET/POST | Sign in |
| `/logout` | GET | Sign out |
| `/api/upload` | POST (multipart `video`) | Start analyzing a video, returns `job_id` |
| `/api/status/<job_id>` | GET | Poll processing progress |
| `/api/analysis/<job_id>` | GET | Full results JSON |
| `/api/history` | GET | All past analyses |
| `/api/dashboard_summary` | GET | Aggregate cards for the Dashboard page |
| `/media/processed/<job_id>.mp4` | GET | Annotated output video |
| `/media/keyframes/<file>`, `/media/heatmaps/<file>` | GET | Images |
| `/api/report/pdf\|excel\|csv/<job_id>` | GET | Downloadable reports |

All routes above require an active session.

## Testing notes
The auth flow, page rendering, and every JSON API endpoint were smoke-tested
against a running Flask test client (login/logout, protected-route
redirects, empty-state responses). The full `VideoJob` pipeline — detection
loop, 4-tier classification, event open/close logic, keyframe capture,
heatmap accumulation, JSON/history persistence, and CSV/Excel export — was
run end-to-end against a synthetic video with a mocked detector (real
YOLOv8 weights aren't downloadable in this offline environment) and
produced correct events, keyframes, and reports. What could **not** be
tested here is the real YOLOv8 model against real footage — run it locally
and share the traceback if anything errors out.

## Troubleshooting
- **`ModuleNotFoundError`** → `pip install -r requirements.txt`.
- **Excel export fails** → `pip install openpyxl` (already in requirements.txt).
- **Upload rejected** → only MP4/AVI/MOV/MKV are accepted; check `MAX_UPLOAD_MB`.
- **Processing is slow** → raise `FRAME_SKIP` in `config.py`, or lower
  `PROCESS_WIDTH`.
- **PDF report says "not available"** → it's generated automatically right
  after processing finishes; check the server console for
  `PDF generation skipped: ...` if it's missing.
- **SMS/Email not sending** → these are off by default except email; check
  console output for `[EMAIL]`/`[SMS]` error lines.

