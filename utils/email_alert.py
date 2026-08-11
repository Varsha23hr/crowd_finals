import smtplib
import ssl
import threading

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config


def _send_sync(subject, body, app):
    try:

        receivers = []

        with app.app_context():
            from models import EmergencyContact

            contacts = EmergencyContact.query.all()

            for contact in contacts:
                if contact.email:
                    receivers.append(contact.email)

        if not receivers:
            receivers = config.RECEIVER_EMAIL

            if isinstance(receivers, str):
                receivers = [receivers]

        message = MIMEMultipart()

        message["From"] = config.SENDER_EMAIL
        message["To"] = ", ".join(receivers)
        message["Subject"] = subject

        message.attach(MIMEText(body, "plain"))

        context = ssl.create_default_context()

        with smtplib.SMTP_SSL(
            config.SMTP_SERVER,
            config.SMTP_PORT,
            context=context,
        ) as server:

            server.login(
                config.SENDER_EMAIL,
                config.SENDER_PASSWORD
            )

            server.sendmail(
                config.SENDER_EMAIL,
                receivers,
                message.as_string()
            )

        print(f"[EMAIL] Alert sent to {receivers}")

    except Exception as exc:
        print(f"[EMAIL] Failed to send alert: {exc}")


def send_alert_email(camera_name, subject_tag, details, app):

    if not config.ENABLE_EMAIL_ALERTS:
        return

    subject = f"[{subject_tag}] {camera_name}"

    body = f"""
Automated Crowd Detection & Overcrowding Alert System
--------------------------------------------------------

Camera : {camera_name}
Type   : {subject_tag}

"""

    for k, v in details.items():
        body += f"{k}: {v}\n"

    threading.Thread(
        target=_send_sync,
        args=(subject, body, app),
        daemon=True
    ).start()