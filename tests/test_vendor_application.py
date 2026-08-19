"""The partner application flow behind ui/Vendor application form.

Business info → location → owner info → documents → review & submit, then the
admin decision and the applicant's path to a working login. Distinct from
tests/test_vendor_registration.py, which covers the password-up-front API fast
path; this is the flow the partner app actually ships.
"""

import re
import uuid

import pytest

pytestmark = pytest.mark.usefixtures("db_available")

V1 = "/api/v1"


def _email() -> str:
    return f"applicant-{uuid.uuid4().hex[:10]}@example.com"


def _application_body(email: str, code: str, **overrides) -> dict:
    body = {
        "otp_code": code,
        "business": {
            "name": f"Kolpatha Restaurant {uuid.uuid4().hex[:6]}",
            "business_type": "RESTAURANT",
            "business_category": "Street Food",
            "branch_count": 1,
            "cuisine_types": ["Fast Food"],
        },
        "location": {
            "address_line": "Road 12, House 42, Nikunja 2, Dhaka",
            "area": "Nikunja 2",
            "latitude": 23.8481,
            "longitude": 90.4148,
        },
        "owner": {
            "full_name": "Hamid Islam",
            "email": email,
            "phone": f"+8801{uuid.uuid4().int % 10**9:09d}",
            "national_id": "454654644564",
        },
        "documents": {
            "shop_image": "https://cdn.example.com/applications/shopkfc.jpg",
            "owner_nid": "https://cdn.example.com/applications/nid_front.jpg",
            "menu_list": "https://cdn.example.com/applications/menu.jpg",
            "trade_license": "https://cdn.example.com/applications/license.pdf",
        },
        "payout": {
            "method": "BKASH",
            "account_name": "Hamid Islam",
            "account_number": "01712447567",
        },
        "agreed_to_terms": True,
    }
    body.update(overrides)
    return body


async def _submit(client, cleanup, **overrides) -> tuple[str, dict]:
    email = _email()
    cleanup(email)
    r = await client.post(f"{V1}/auth/otp/send", json={"email": email, "role": "VENDOR"})
    assert r.status_code == 200, r.text
    code = r.json()["data"]["debug_code"]

    r = await client.post(
        f"{V1}/vendor/applications", json=_application_body(email, code, **overrides)
    )
    assert r.status_code == 201, r.text
    return email, r.json()["data"]


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


async def test_submission_returns_a_quotable_reference(client, cleanup_users, reset_limits):
    _, data = await _submit(client, cleanup_users)

    assert re.fullmatch(r"PTN-\d{5,7}", data["application_no"]), data["application_no"]
    assert data["status"] == "PENDING"
    assert data["restaurant_id"]
    assert "2–3 business days" in data["message"]


async def test_no_password_means_no_login_until_approval_flow(
    client, cleanup_users, reset_limits
):
    """The form never asks for a password, so the account must not be
    sign-in-able until the owner sets one via the OTP reset flow."""
    email, _ = await _submit(client, cleanup_users)

    r = await client.post(f"{V1}/auth/login", json={"email": email, "password": "Anything1!"})
    assert r.status_code == 401, r.text


async def test_submission_requires_a_valid_otp(client, cleanup_users, reset_limits):
    email = _email()
    cleanup_users(email)
    r = await client.post(f"{V1}/auth/otp/send", json={"email": email, "role": "VENDOR"})
    assert r.status_code == 200

    r = await client.post(
        f"{V1}/vendor/applications", json=_application_body(email, "0000")
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "INVALID_OTP"


async def test_terms_checkbox_is_mandatory(client, cleanup_users, reset_limits):
    """And a refusal must not consume the OTP — the same code works after."""
    email = _email()
    cleanup_users(email)
    r = await client.post(f"{V1}/auth/otp/send", json={"email": email, "role": "VENDOR"})
    code = r.json()["data"]["debug_code"]

    r = await client.post(
        f"{V1}/vendor/applications",
        json=_application_body(email, code, agreed_to_terms=False),
    )
    assert r.status_code == 400, r.text

    r = await client.post(f"{V1}/vendor/applications", json=_application_body(email, code))
    assert r.status_code == 201, "the terms rejection burned the OTP"


async def test_missing_required_document_is_rejected(client, cleanup_users, reset_limits):
    email = _email()
    cleanup_users(email)
    r = await client.post(f"{V1}/auth/otp/send", json={"email": email, "role": "VENDOR"})
    code = r.json()["data"]["debug_code"]

    body = _application_body(email, code)
    del body["documents"]["owner_nid"]
    r = await client.post(f"{V1}/vendor/applications", json=body)
    assert r.status_code == 400, r.text


async def test_customer_email_cannot_apply(
    client, cleanup_users, reset_limits, customer_user, clear_cooldowns
):
    r = await client.post(
        f"{V1}/auth/otp/send", json={"email": customer_user.email, "role": "VENDOR"}
    )
    assert r.status_code == 200
    code = r.json()["data"]["debug_code"]

    r = await client.post(
        f"{V1}/vendor/applications", json=_application_body(customer_user.email, code)
    )
    assert r.status_code == 409, r.text


async def test_one_application_per_email(client, cleanup_users, reset_limits, clear_cooldowns):
    email, first = await _submit(client, cleanup_users)

    await clear_cooldowns()
    r = await client.post(f"{V1}/auth/otp/send", json={"email": email, "role": "VENDOR"})
    code = r.json()["data"]["debug_code"]
    r = await client.post(f"{V1}/vendor/applications", json=_application_body(email, code))
    assert r.status_code == 409, r.text
    # The 409 hands back the existing reference so the applicant is not stuck.
    assert first["application_no"] in r.json()["error"]["message"]


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------


async def test_status_needs_reference_and_email_together(client, cleanup_users, reset_limits):
    email, data = await _submit(client, cleanup_users)
    no = data["application_no"]

    r = await client.get(f"{V1}/vendor/applications/{no}", params={"email": email})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "PENDING"
    assert r.json()["data"]["review_note"] is None

    r = await client.get(
        f"{V1}/vendor/applications/{no}", params={"email": "someone-else@example.com"}
    )
    assert r.status_code == 404, "a wrong email must look identical to a wrong reference"


# ---------------------------------------------------------------------------
# The admin decision
# ---------------------------------------------------------------------------


async def _pending_ids(client, admin: dict) -> list[str]:
    r = await client.get(f"{V1}/admin/vendor-applications", headers=admin)
    assert r.status_code == 200, r.text
    return [a["id"] for a in r.json()["data"]]


async def test_approval_verifies_restaurant_and_unlocks_login(
    client, cleanup_users, reset_limits, admin_token, clear_cooldowns
):
    """The whole happy path: apply → approve → set password → sign in → the
    vendor sees their own verified restaurant."""
    email, data = await _submit(client, cleanup_users)
    admin = {"Authorization": f"Bearer {admin_token}"}

    # Find it in the queue and read the detail an admin decides on
    r = await client.get(f"{V1}/admin/vendor-applications", headers=admin)
    row = next(a for a in r.json()["data"] if a["application_no"] == data["application_no"])
    assert row["national_id"] == "454654644564"
    assert row["documents"]["owner_nid"]
    assert row["payout"]["method"] == "BKASH"

    r = await client.post(
        f"{V1}/admin/vendor-applications/{row['id']}/approve", json={}, headers=admin
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["application"]["status"] == "APPROVED"

    # Status flips for the applicant
    r = await client.get(
        f"{V1}/vendor/applications/{data['application_no']}", params={"email": email}
    )
    assert r.json()["data"]["status"] == "APPROVED"

    # The approval email points at the OTP password flow — walk it
    await clear_cooldowns()
    r = await client.post(f"{V1}/auth/password/forgot", json={"email": email})
    code = r.json()["data"]["debug_code"]
    r = await client.post(
        f"{V1}/auth/password/reset",
        json={"email": email, "code": code, "new_password": "PartnerPass1!"},
    )
    assert r.status_code == 200, r.text

    r = await client.post(f"{V1}/auth/login", json={"email": email, "password": "PartnerPass1!"})
    assert r.status_code == 200, r.text
    token = r.json()["data"]["tokens"]["access_token"]

    r = await client.get(
        f"{V1}/vendor/profile", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_verified"] is True
    assert r.json()["data"]["status"] == "CLOSED", "approval must not open the store"


async def test_rejection_records_reason_for_the_applicant(
    client, cleanup_users, reset_limits, admin_token
):
    email, data = await _submit(client, cleanup_users)
    admin = {"Authorization": f"Bearer {admin_token}"}

    r = await client.get(f"{V1}/admin/vendor-applications", headers=admin)
    row = next(a for a in r.json()["data"] if a["application_no"] == data["application_no"])

    r = await client.post(
        f"{V1}/admin/vendor-applications/{row['id']}/reject",
        json={"note": "Trade license is unreadable"},
        headers=admin,
    )
    assert r.status_code == 200, r.text

    # The applicant sees the reason; the restaurant never becomes visible
    r = await client.get(
        f"{V1}/vendor/applications/{data['application_no']}", params={"email": email}
    )
    assert r.json()["data"]["status"] == "REJECTED"
    assert r.json()["data"]["review_note"] == "Trade license is unreadable"

    # Decisions are final
    r = await client.post(
        f"{V1}/admin/vendor-applications/{row['id']}/approve", json={}, headers=admin
    )
    assert r.status_code == 400, "a rejected application was re-decided"


async def test_decided_applications_leave_the_default_queue(
    client, cleanup_users, reset_limits, admin_token
):
    _, data = await _submit(client, cleanup_users)
    admin = {"Authorization": f"Bearer {admin_token}"}

    r = await client.get(f"{V1}/admin/vendor-applications", headers=admin)
    row = next(a for a in r.json()["data"] if a["application_no"] == data["application_no"])

    await client.post(
        f"{V1}/admin/vendor-applications/{row['id']}/approve", json={}, headers=admin
    )
    assert row["id"] not in await _pending_ids(client, admin)

    r = await client.get(
        f"{V1}/admin/vendor-applications", params={"status": "APPROVED"}, headers=admin
    )
    assert row["id"] in [a["id"] for a in r.json()["data"]]


async def test_only_admins_review(client, cleanup_users, reset_limits, customer_token):
    _, data = await _submit(client, cleanup_users)
    headers = {"Authorization": f"Bearer {customer_token}"}

    r = await client.get(f"{V1}/admin/vendor-applications", headers=headers)
    assert r.status_code == 403

    r = await client.post(
        f"{V1}/admin/vendor-applications/{uuid.uuid4()}/approve", json={}, headers=headers
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Document uploads
# ---------------------------------------------------------------------------


async def test_application_upload_is_public_but_validated(client, reset_limits):
    """No auth header. 503 (not configured) locally is the pass condition —
    what matters is that it never 401s and never signs a forbidden type."""
    r = await client.post(
        f"{V1}/vendor/applications/uploads", json={"file_type": "application/pdf"}
    )
    assert r.status_code in (200, 503), r.text
    if r.status_code == 200:
        assert r.json()["data"]["key"].startswith("applications/")

    r = await client.post(
        f"{V1}/vendor/applications/uploads", json={"file_type": "text/html"}
    )
    assert r.status_code == 400, "text/html must never be signable"
