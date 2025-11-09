from __future__ import annotations

import os
import json
import smtplib
from email.message import EmailMessage
from urllib import request as urlrequest

class Notifier:
    """
    Notifiche admin:
      - Console (sempre)
      - Email SMTP (se configurato)
      - Webhook HTTP POST (se configurato)
    Variabili d'ambiente:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TO, SMTP_TLS (1/0)
      NOTIFY_WEBHOOK_URL
    """
    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_pass = os.getenv("SMTP_PASS")
        self.smtp_from = os.getenv("SMTP_FROM")
        self.smtp_to   = os.getenv("SMTP_TO")
        self.smtp_tls  = os.getenv("SMTP_TLS", "1") not in ("0", "false", "False", "")

        self.webhook_url = os.getenv("NOTIFY_WEBHOOK_URL")

    # ---------------------- channels ----------------------

    def _console(self, title: str, payload: dict):
        print(f"[ADMIN-NOTIFY] {title} :: {json.dumps(payload, ensure_ascii=False)}")

    def _email(self, subject: str, payload: dict):
        if not (self.smtp_host and self.smtp_from and self.smtp_to):
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp_from
        msg["To"] = self.smtp_to
        msg.set_content(json.dumps(payload, indent=2, ensure_ascii=False))

        if self.smtp_tls:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as s:
                s.starttls()
                if self.smtp_user and self.smtp_pass:
                    s.login(self.smtp_user, self.smtp_pass)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as s:
                if self.smtp_user and self.smtp_pass:
                    s.login(self.smtp_user, self.smtp_pass)
                s.send_message(msg)
        return True

    def _webhook(self, payload: dict):
        if not self.webhook_url:
            return False
        data = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=10) as _resp:  # nosec - trusted admin URL
            _ = _.read()
        return True

    # ---------------------- public API ----------------------

    def notify(self, title: str, payload: dict) -> dict:
        """Invia su tutti i canali configurati."""
        sent = {"console": False, "email": False, "webhook": False}
        try:
            self._console(title, payload); sent["console"] = True
        except Exception:
            pass
        try:
            sent["email"] = bool(self._email(f"[VoiceGuide] {title}", payload))
        except Exception:
            pass
        try:
            sent["webhook"] = bool(self._webhook({"title": title, "payload": payload}))
        except Exception:
            pass
        return sent
