"""Outbound email delivery. SMTP when configured (SMTP_HOST + EMAIL_FROM), otherwise nothing leaves the system.

Credentials live only in the backend environment; the browser extension never sees them or the recipient address.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import get_settings

log = logging.getLogger("churnce.mailer")
settings = get_settings()


class MailError(Exception):
    pass


def configured() -> bool:
    return bool(settings.smtp_host and settings.email_from)


def delivery_mode() -> str:
    return "smtp" if configured() else "simulated"


def send(to: str, subject: str, body: str) -> str:
    """Send one plain-text message. Returns the Message-ID. Raises MailError with a safe message on failure."""
    if not configured():
        raise MailError("SMTP is not configured")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.email_from, to, subject
    msg["Date"], msg["Message-ID"] = formatdate(localtime=False), make_msgid(domain=settings.email_from.split("@")[-1] or None)
    if settings.email_reply_to:
        msg["Reply-To"] = settings.email_reply_to
    msg["List-Unsubscribe"] = f"<mailto:{settings.email_reply_to or settings.email_from}?subject=unsubscribe>"
    msg.set_content(f"{body.rstrip()}\n\n--\n{settings.email_footer}")
    try:
        ctx = ssl.create_default_context()
        if settings.smtp_port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=ctx)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
            if settings.smtp_starttls:
                server.starttls(context=ctx)
        with server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("SMTP delivery failed: %s", str(exc)[:160])
        raise MailError(f"Mail server rejected or could not be reached: {str(exc)[:120]}") from exc
    return str(msg["Message-ID"])
