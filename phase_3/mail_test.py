"""
phase_3/mail_test.py
--------------------
Development-only email sender for testing the digest pipeline end-to-end
without needing the Open Paws platform infrastructure.

Reads test recipient addresses from phase_3/test_recipients.yaml and sends
the compiled DigestPackage to all listed addresses via SMTP.

This module is intentionally separate from the production platform_handoff.py
so the testing path can never be confused with the live delivery path.

Usage
-----
Called by POST /phase3/mail/test in router.py. Can also be run standalone:
    python -m phase_3.mail_test

Required environment variables (add to .env):
    SMTP_HOST      - SMTP server host (e.g. smtp.gmail.com)
    SMTP_PORT      - SMTP server port (e.g. 465 for SSL, 587 for STARTTLS)
    SMTP_USER      - SMTP login username (usually your email address)
    SMTP_PASSWORD  - SMTP password or App Password
    SMTP_FROM      - Sender display string (e.g. "Open Paws Sentinel <you@gmail.com>")

Gmail setup:
    1. Enable 2FA on your Google account
    2. Go to myaccount.google.com → Security → App Passwords
    3. Generate a password for "Mail" / "Other"
    4. Use that 16-char password as SMTP_PASSWORD
    5. Set SMTP_HOST=smtp.gmail.com, SMTP_PORT=465
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_RECIPIENTS_FILE = Path(__file__).parent / "test_recipients.yaml"

SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER: Optional[str] = os.environ.get("SMTP_USER")
SMTP_PASSWORD: Optional[str] = os.environ.get("SMTP_PASSWORD")
SMTP_FROM: str = os.environ.get("SMTP_FROM", "Open Paws Sentinel <noreply@example.com>")


# ---------------------------------------------------------------------------
# Recipient loader
# ---------------------------------------------------------------------------

def load_test_recipients() -> List[str]:
    """
    Load test recipient email addresses from test_recipients.yaml.

    Returns a flat list of email address strings.
    Skips any entry that is commented out or marked enabled: false.
    """
    if not _RECIPIENTS_FILE.exists():
        raise FileNotFoundError(
            f"test_recipients.yaml not found at {_RECIPIENTS_FILE}. "
            "Create it from the example in phase_3/."
        )

    with open(_RECIPIENTS_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    recipients_raw = data.get("recipients", [])
    active: List[str] = []

    for entry in recipients_raw:
        if isinstance(entry, str):
            # Simple string form: just an email address
            active.append(entry.strip())
        elif isinstance(entry, dict):
            # Dict form: {email: "...", name: "...", enabled: true}
            if entry.get("enabled", True):
                email = entry.get("email", "").strip()
                if email:
                    active.append(email)

    if not active:
        raise ValueError(
            "No active recipients found in test_recipients.yaml. "
            "Add at least one recipient with enabled: true."
        )

    return active


# ---------------------------------------------------------------------------
# SMTP send
# ---------------------------------------------------------------------------

def _build_message(
    recipient: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> MIMEMultipart:
    """Build a MIME multipart/alternative email message."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = recipient
    msg["X-Test-Mailer"] = "OpenPaws-Phase3-TestMailer"

    # Plain text first (fallback), then HTML (preferred)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    return msg


def send_test_digest(
    html_body: str,
    text_body: str,
    digest_date: date,
    recipients: Optional[List[str]] = None,
) -> dict:
    """
    Send the compiled digest to all test recipients via SMTP.

    Args:
        html_body:    Rendered HTML email body from DigestPackage.
        text_body:    Rendered plain-text body from DigestPackage.
        digest_date:  The date the digest covers (used in subject line).
        recipients:   Optional override list of addresses. If None, loads
                      from test_recipients.yaml.

    Returns:
        Dict with keys: sent (list of addresses), failed (list), total.

    Raises:
        EnvironmentError: If SMTP_USER or SMTP_PASSWORD are not set.
        FileNotFoundError: If test_recipients.yaml is missing.
        ValueError: If no active recipients are found.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        raise EnvironmentError(
            "SMTP_USER and SMTP_PASSWORD must be set in the environment "
            "before sending test emails. See phase_3/mail_test.py for setup."
        )

    if recipients is None:
        recipients = load_test_recipients()

    subject = (
        f"[TEST] Open Paws Federal Register Sentinel — "
        f"{digest_date.strftime('%B %d, %Y')}"
    )

    sent: List[str] = []
    failed: List[str] = []

    # Use SSL (port 465). For STARTTLS (port 587), swap to smtplib.SMTP + starttls().
    context = ssl.create_default_context()

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            logger.info(
                "[MailTest] Connected to %s:%d as %s",
                SMTP_HOST, SMTP_PORT, SMTP_USER,
            )

            for recipient in recipients:
                try:
                    msg = _build_message(recipient, subject, html_body, text_body)
                    server.sendmail(SMTP_USER, recipient, msg.as_string())
                    sent.append(recipient)
                    logger.info("[MailTest] Sent to %s", recipient)
                except smtplib.SMTPException as exc:
                    failed.append(recipient)
                    logger.error("[MailTest] Failed to send to %s: %s", recipient, exc)

    except smtplib.SMTPAuthenticationError as exc:
        raise EnvironmentError(
            f"SMTP authentication failed for {SMTP_USER}. "
            "Check SMTP_USER and SMTP_PASSWORD. "
            "For Gmail, make sure you are using an App Password, not your account password. "
            f"Original error: {exc}"
        ) from exc

    logger.info(
        "[MailTest] Done. Sent: %d, Failed: %d",
        len(sent), len(failed),
    )

    return {
        "sent": sent,
        "failed": failed,
        "total": len(recipients),
        "subject": subject,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Standalone runner (python -m phase_3.mail_test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    from phase_3.db import init_db
    from phase_3.digest_builder import build_digest
    from phase_3.digest_query import fetch_digest_rows

    async def _run() -> None:
        init_db()
        today = datetime.now(timezone.utc).date()
        rows = await fetch_digest_rows(today)
        package = build_digest(rows, today)

        result = send_test_digest(
            html_body=package.html_body,
            text_body=package.text_body,
            digest_date=package.digest_date,
        )
        print("\n=== Test Mail Result ===")
        for k, v in result.items():
            print(f"  {k}: {v}")

    asyncio.run(_run())
