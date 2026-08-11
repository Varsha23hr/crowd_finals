import random
import smtplib
import ssl

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config


def generate_otp():
    """Return a random 6-digit OTP."""
    return str(random.randint(100000, 999999))


def send_otp_email(receiver_email, otp):

    subject = "Crowd Alert System - Password Reset OTP"

    body = f"""
Hello,

A password reset request was received for your Crowd Alert System account.

Your One-Time Password (OTP) is:

==========================
        {otp}
==========================

This OTP is valid for 5 minutes.

If you did not request this password reset, you can safely ignore this email.

Regards,
Crowd Alert System
"""

    message = MIMEMultipart()

    message["From"] = config.SENDER_EMAIL
    message["To"] = receiver_email
    message["Subject"] = subject

    message.attach(MIMEText(body, "plain"))

    context = ssl.create_default_context()

    with smtplib.SMTP_SSL(
        config.SMTP_SERVER,
        config.SMTP_PORT,
        context=context
    ) as server:

        server.login(
            config.SENDER_EMAIL,
            config.SENDER_PASSWORD
        )

        server.sendmail(
            config.SENDER_EMAIL,
            receiver_email,
            message.as_string()
        )

    print(f"[OTP] Email sent to {receiver_email}")