"""Transactional email delivery via Resend.

**Sent inline, not queued.** An OTP is worthless five minutes after it is
requested, and the user is sitting on a loading spinner waiting for it. Pushing
it onto arq would add a failure mode with no upside: a stopped worker would mean
every signup silently receives nothing while the API happily returns 200. A
10-second timeout bounds the latency, and a failure is visible in the response
path rather than buried in a queue.

Bulk or non-urgent mail (receipts, weekly summaries) should still go through arq
when it arrives — that is what the queue is good at.
"""

from __future__ import annotations

import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger()

RESEND_ENDPOINT = "https://api.resend.com/emails"


class EmailDeliveryError(Exception):
    """Raised when the provider rejects or fails to accept a message."""


async def _post(payload: dict) -> str:
    """Hand a message to Resend. Returns the provider's message id."""
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=settings.EMAIL_TIMEOUT_SECONDS) as client:
        response = await client.post(RESEND_ENDPOINT, json=payload, headers=headers)

    if response.status_code >= 400:
        # Resend's own message is the useful part — surface it in logs, never to
        # the caller.
        raise EmailDeliveryError(f"{response.status_code}: {response.text[:300]}")

    return response.json().get("id", "")


async def send_email(to: str, subject: str, html: str, text: str) -> str | None:
    """Send one message. Returns the provider message id, or None if disabled.

    Raises EmailDeliveryError on provider failure. Callers decide whether that
    is fatal — for `/auth/password/forgot` it must NOT be, because a delivery
    error distinguishable from success would leak whether the account exists.
    """
    if not settings.email_enabled:
        # Development convenience: no Resend account needed to work on the app.
        log.warning("email_disabled_not_sent", to=to, subject=subject)
        return None

    sender = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
    payload: dict = {"from": sender, "to": [to], "subject": subject, "html": html, "text": text}
    if settings.EMAIL_REPLY_TO:
        payload["reply_to"] = settings.EMAIL_REPLY_TO

    message_id = await _post(payload)
    log.info("email_sent", to_domain=to.split("@")[-1], subject=subject, message_id=message_id)
    return message_id


# ---------------------------------------------------------------------------
# Templates
#
# Inline CSS and a table-free layout on purpose: Gmail strips <style> blocks,
# and Outlook's rendering engine is Word. A plain-text alternative is always
# included — some clients show it, and messages without one score worse with
# spam filters.
# ---------------------------------------------------------------------------

_BASE = """<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f4f5;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <div style="max-width:480px;margin:0 auto;padding:32px 24px;">
    <div style="background:#ffffff;border-radius:12px;padding:32px;
                box-shadow:0 1px 3px rgba(0,0,0,0.08);">
      <h1 style="margin:0 0 8px;font-size:20px;color:#18181b;">{heading}</h1>
      <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#52525b;">{intro}</p>
      <div style="background:#f4f4f5;border-radius:8px;padding:20px;text-align:center;
                  margin:0 0 24px;">
        <div style="font-size:32px;font-weight:700;letter-spacing:8px;
                    color:#18181b;font-family:'SF Mono',Menlo,Consolas,monospace;">{code}</div>
      </div>
      <p style="margin:0 0 8px;font-size:13px;line-height:1.6;color:#71717a;">
        This code expires in {minutes} minutes.</p>
      <p style="margin:0;font-size:13px;line-height:1.6;color:#71717a;">{footer}</p>
    </div>
    <p style="margin:24px 0 0;font-size:12px;text-align:center;color:#a1a1aa;">
      {brand} &middot; This is an automated message.</p>
  </div>
</body></html>"""


def _minutes() -> int:
    return max(settings.OTP_TTL_SECONDS // 60, 1)


def signup_otp(code: str) -> tuple[str, str, str]:
    """(subject, html, text) for account verification."""
    minutes = _minutes()
    brand = settings.EMAIL_FROM_NAME
    subject = f"{code} is your {brand} verification code"
    html = _BASE.format(
        heading="Verify your account",
        intro="Enter this code to finish creating your account.",
        code=code,
        minutes=minutes,
        footer="If you did not request this, you can safely ignore this email.",
        brand=brand,
    )
    text = (
        f"Verify your account\n\n"
        f"Your {brand} verification code is: {code}\n\n"
        f"It expires in {minutes} minutes.\n"
        f"If you did not request this, you can safely ignore this email.\n"
    )
    return subject, html, text


def password_reset_otp(code: str) -> tuple[str, str, str]:
    """(subject, html, text) for password reset."""
    minutes = _minutes()
    brand = settings.EMAIL_FROM_NAME
    subject = f"{code} is your {brand} password reset code"
    html = _BASE.format(
        heading="Reset your password",
        intro="Enter this code to choose a new password.",
        code=code,
        minutes=minutes,
        footer=(
            "If you did not request a password reset, ignore this email — "
            "your password has not changed."
        ),
        brand=brand,
    )
    text = (
        f"Reset your password\n\n"
        f"Your {brand} password reset code is: {code}\n\n"
        f"It expires in {minutes} minutes.\n"
        f"If you did not request this, your password has not changed.\n"
    )
    return subject, html, text


def check_email_config() -> dict:
    """Readiness detail. A deployed environment with no key is misconfigured."""
    if settings.email_enabled:
        return {"status": "ok", "from": settings.EMAIL_FROM}
    if settings.ENVIRONMENT in {"local", "test"}:
        return {"status": "disabled", "detail": "no RESEND_API_KEY (fine locally)"}
    return {"status": "error", "detail": "RESEND_API_KEY is not set"}
