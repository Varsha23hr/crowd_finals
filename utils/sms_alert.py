"""
utils/sms_alert.py
Sends overcrowding / anomaly alert SMS messages via Twilio on a background
thread. Only activates if config.ENABLE_SMS_ALERTS is True.

Install: pip install twilio
"""

import threading

import config


def _send_sync(body: str) -> None:
    try:
        from twilio.rest import Client  # imported lazily so the package is
        # only required when SMS alerts are actually enabled.

        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=config.TWILIO_FROM_NUMBER,
            to=config.TWILIO_TO_NUMBER,
        )
        print(f"[SMS] Alert sent, SID={message.sid}")
    except Exception as exc:
        print(f"[SMS] Failed to send alert: {exc}")


def send_sms_alert(camera_name: str, subject_tag: str, details: dict) -> None:
    if not config.ENABLE_SMS_ALERTS:
        return
    lines = [f"[{subject_tag}] {camera_name}"]
    for k, v in details.items():
        lines.append(f"{k}: {v}")
    body = "\n".join(lines)[:1500]  # keep well under SMS length limits

    threading.Thread(target=_send_sync, args=(body,), daemon=True).start()
