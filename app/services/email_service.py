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
    # The code is deliberately NOT in the subject. Subject lines are rendered in
    # lock-screen notification previews, so anyone holding the phone could read
    # the code without unlocking it. Nothing is lost: OS autofill reads the body.
    subject = f"Verify your {brand} account"
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
    # See the note in signup_otp — kept out of the subject on purpose.
    subject = f"Reset your {brand} password"
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


# A code-free variant of _BASE for messages rather than OTPs. Same inline-CSS
# constraints; {body} is one or more <p> blocks.
_MESSAGE_BASE = """<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f4f5;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <div style="max-width:480px;margin:0 auto;padding:32px 24px;">
    <div style="background:#ffffff;border-radius:12px;padding:32px;
                box-shadow:0 1px 3px rgba(0,0,0,0.08);">
      <h1 style="margin:0 0 8px;font-size:20px;color:#18181b;">{heading}</h1>
      {body}
    </div>
    <p style="margin:24px 0 0;font-size:12px;text-align:center;color:#a1a1aa;">
      {brand} &middot; This is an automated message.</p>
  </div>
</body></html>"""

_P = '<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#52525b;">{}</p>'


def application_received(application_no: str, business_name: str) -> tuple[str, str, str]:
    """(subject, html, text) confirming a partner application was submitted."""
    brand = settings.EMAIL_FROM_NAME
    subject = f"We received your {brand} partner application"
    paragraphs = [
        f"Thanks for applying to sell on {brand} with <strong>{business_name}</strong>.",
        f"Your application reference is <strong>{application_no}</strong>. "
        "Keep it — support will ask for it.",
        "We review every application by hand and will get back to you within "
        "2–3 business days by email.",
    ]
    html = _MESSAGE_BASE.format(
        heading="Application submitted",
        body="".join(_P.format(p) for p in paragraphs),
        brand=brand,
    )
    text = (
        f"Application submitted\n\n"
        f"Thanks for applying to sell on {brand} with {business_name}.\n"
        f"Your application reference is {application_no}.\n\n"
        f"We review every application by hand and will get back to you within "
        f"2-3 business days by email.\n"
    )
    return subject, html, text


def application_approved(business_name: str, owner_email: str) -> tuple[str, str, str]:
    """(subject, html, text) for an approved partner application.

    The next step is deliberately the OTP password flow, not a link with an
    embedded token: the apps already implement that flow, and an email that
    tells the user to request their own code cannot be replayed from a
    forwarded inbox.
    """
    brand = settings.EMAIL_FROM_NAME
    subject = f"Your {brand} partner account is ready"
    steps = (
        f"Open the {brand} Partner app and choose <strong>Login</strong>, then "
        f"<strong>Forgot Password</strong>. Enter <strong>{owner_email}</strong>, "
        "type the code we send you, and set your password. That's it — you can "
        "then sign in, finish your menu and open your store."
    )
    paragraphs = [
        f"Good news — <strong>{business_name}</strong> has been approved and your "
        "partner account is ready.",
        steps,
    ]
    html = _MESSAGE_BASE.format(
        heading="Welcome! Your partner account is ready",
        body="".join(_P.format(p) for p in paragraphs),
        brand=brand,
    )
    text = (
        f"Welcome! Your partner account is ready\n\n"
        f"Good news - {business_name} has been approved.\n\n"
        f"To sign in: open the {brand} Partner app, choose Login, then Forgot "
        f"Password. Enter {owner_email}, type the code we send you, and set "
        f"your password. You can then sign in, finish your menu and open your "
        f"store.\n"
    )
    return subject, html, text


def application_rejected(business_name: str, reason: str | None) -> tuple[str, str, str]:
    """(subject, html, text) for a rejected partner application."""
    brand = settings.EMAIL_FROM_NAME
    subject = f"About your {brand} partner application"
    detail = reason or "It did not meet our current partner requirements."
    paragraphs = [
        f"Thank you for applying to sell on {brand} with "
        f"<strong>{business_name}</strong>. After review, we are unable to "
        "approve your application at this time.",
        f"<strong>Reason:</strong> {detail}",
        "If you believe this is a mistake, or you can address the reason above, "
        "reply to this email and our team will take another look.",
    ]
    html = _MESSAGE_BASE.format(
        heading="Your application was not approved",
        body="".join(_P.format(p) for p in paragraphs),
        brand=brand,
    )
    text = (
        f"Your application was not approved\n\n"
        f"Thank you for applying to sell on {brand} with {business_name}. "
        f"After review, we are unable to approve your application at this time.\n\n"
        f"Reason: {detail}\n\n"
        f"If you believe this is a mistake, or you can address the reason "
        f"above, reply to this email and our team will take another look.\n"
    )
    return subject, html, text


def check_email_config() -> dict:
    """Readiness detail. A deployed environment with no key is misconfigured."""
    if settings.email_enabled:
        return {"status": "ok", "from": settings.EMAIL_FROM}
    if settings.ENVIRONMENT in {"local", "test"}:
        return {"status": "disabled", "detail": "no RESEND_API_KEY (fine locally)"}
    return {"status": "error", "detail": "RESEND_API_KEY is not set"}
