"""Send the daily summary by email.

Uses Resend's HTTPS API (works in sandboxes that only allow outbound HTTPS).
RESEND_API_KEY is optional there because the egress proxy injects the
Authorization header. Local runs without a Resend key can use SMTP instead.
"""
import smtplib
from email.message import EmailMessage

import requests

from .config import Config

RESEND_URL = "https://api.resend.com/emails"


def send_email(cfg: Config, subject: str, body: str) -> None:
    if not cfg.use_smtp:
        headers = {"Authorization": f"Bearer {cfg.resend_api_key}"} if cfg.resend_api_key else {}
        resp = requests.post(
            RESEND_URL,
            headers=headers,
            json={"from": cfg.email_from, "to": [cfg.email_to], "subject": subject, "text": body},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Resend -> {resp.status_code}: {resp.text[:300]}")
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg.smtp_user, cfg.email_to
    msg.set_content(body)
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(msg)
