import smtplib
from email.message import EmailMessage

from .config import Config


def send_email(cfg: Config, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, cfg.smtp_user, cfg.email_to
    msg.set_content(body)
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(msg)
