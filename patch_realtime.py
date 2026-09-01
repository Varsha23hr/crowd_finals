with open('video_processor.py', 'r') as f:
    vp = f.read()

# 1. Add _last_alert_time tracking in __init__ (after self.fallback_model line)
old_init = "        self.fallback_model = fallback_model"
new_init = """        self.fallback_model = fallback_model
        self._last_realtime_alert_t = -999  # cooldown tracker for real-time alerts"""

if "_last_realtime_alert_t" not in vp:
    vp = vp.replace(old_init, new_init)

# 2. Inject real-time alert trigger after status is determined and siren logic
old_siren = """            status = self._classify(person_count)
            if person_count >= self.threshold:
                play_siren()
            else:
                stop_siren()"""

new_siren = """            status = self._classify(person_count)
            if person_count >= self.threshold:
                play_siren()
            else:
                stop_siren()

            # --- Real-time email alert (fires immediately when HIGH/CRITICAL) ---
            ALERT_COOLDOWN_SECONDS = 60  # only send once per minute max
            if status in ("HIGH", "CRITICAL"):
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
                        print(f"[VideoJob {self.job_id}] Real-time alert failed: {_e}")"""

if "Real-time email alert" not in vp:
    vp = vp.replace(old_siren, new_siren)

with open('video_processor.py', 'w') as f:
    f.write(vp)

print("Patch applied successfully!")
