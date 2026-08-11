"""Utility functions for sending alerts based on stored AlertSetting preferences.

This module provides a simple wrapper that reads the AlertSetting from the database
and dispatches email and SMS alerts using the existing utils.email_alert and
utils.sms_alert helpers. WhatsApp notifications are left as a placeholder.
"""


from .email_alert import send_alert_email
from .sms_alert import send_sms_alert
from models import AlertSetting, AlertHistory, EmergencyContact, db
from datetime import datetime
import json

def get_active_setting():
    """Retrieve the first AlertSetting row, or create a default one if none exist."""
    setting = AlertSetting.query.first()
    if not setting:
        setting = AlertSetting()
        db.session.add(setting)
        db.session.commit()
    return setting

def send_alert(camera_name: str, severity: str, details: dict):
    """Send alerts according to the stored preferences.

    Parameters
    ----------
    camera_name: str
        Identifier of the camera or video source.
    severity: str
        One of "WARNING", "HIGH", "CRITICAL".
    details: dict
        Additional details to include in the notification body.
    """
    setting = get_active_setting()
    # Record in history regardless of preferences
    contacts = [c.to_dict() for c in EmergencyContact.query.all()]
    history = AlertHistory(
        # pyrefly: ignore [unexpected-keyword]
        location=details.get('location', ''),
        # pyrefly: ignore [unexpected-keyword]
        camera_name=camera_name,
        # pyrefly: ignore [unexpected-keyword]
        crowd_count=details.get('crowd_count'),
        # pyrefly: ignore [unexpected-keyword]
        threshold=details.get('threshold'),
        # pyrefly: ignore [unexpected-keyword]
        severity=severity,
        # pyrefly: ignore [unexpected-keyword]
        contacts_json=json.dumps(contacts)
    )
    
    db.session.add(history)
    db.session.commit()

    subject_tag = f"{severity} OVERCROWDING"
    if setting.notify_email:
        send_alert_email(camera_name, subject_tag, details)
    if setting.notify_sms:
        send_sms_alert(camera_name, subject_tag, details)
    # WhatsApp placeholder – could be integrated with a service like Twilio.
    if setting.notify_whatsapp:
        # TODO: integrate WhatsApp API
        pass
