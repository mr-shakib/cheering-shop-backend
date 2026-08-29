"""The frontend documentation must stay true.

The `docs/*-API.md` files are sent to the mobile team and built against. A
number that drifts from the code — a token lifetime, a rate limit, an endpoint
that quietly disappeared — costs them a debugging session and costs us their
trust in the document. These tests fail the build rather than let that happen.

Endpoint coverage is checked across **every** API doc rather than one file, so
adding a module means adding its doc: an implemented endpoint that appears in no
document fails here, and so does a documented endpoint that is still a 501 stub.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DOC = DOCS / "AUTH-API.md"
VENDOR_DOC = DOCS / "VENDOR-API.md"
CUSTOMER_DOC = DOCS / "CUSTOMER-API.md"
RIDER_DOC = DOCS / "RIDER-API.md"
ENDPOINTS = ROOT / "app" / "api" / "v1" / "endpoints"

# Every document that carries an endpoint summary table. A new module's doc
# belongs here, or its endpoints will read as undocumented.
API_DOCS = (DOC, VENDOR_DOC, CUSTOMER_DOC, RIDER_DOC)


def _normalise(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{id}", path)


def _implemented() -> set[tuple[str, str]]:
    """Every route that is actually built (not a 501 stub)."""
    found: set[tuple[str, str]] = set()
    for file in sorted(ENDPOINTS.glob("*.py")):
        if file.name == "__init__.py":
            continue
        tree = ast.parse(file.read_text())
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter":
                for kw in node.keywords:
                    if kw.arg == "prefix":
                        prefix = kw.value.value
        for node in tree.body:
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                method = getattr(dec.func, "attr", "")
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if "NotImplementedYetError" in ast.dump(node):
                    continue
                path = dec.args[0].value if dec.args else ""
                found.add((method.upper(), _normalise(prefix + path)))
    return found


def _documented() -> set[tuple[str, str]]:
    """Rows of every API doc's endpoint summary table."""
    found: set[tuple[str, str]] = set()
    for doc in API_DOCS:
        assert doc.exists(), f"{doc.relative_to(ROOT)} is missing"
        found |= {
            (m.group(1), _normalise(m.group(2)))
            for m in re.finditer(
                r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`", doc.read_text(), re.M
            )
        }
    return found


def test_every_implemented_endpoint_is_documented():
    missing = _implemented() - _documented()
    assert not missing, (
        "implemented but absent from docs/AUTH-API.md — the frontend team "
        f"cannot use what they cannot see: {sorted(missing)}"
    )


def test_docs_promise_nothing_that_does_not_exist():
    extra = _documented() - _implemented()
    assert not extra, (
        "documented but not implemented — the team will build against these and "
        f"get a 501: {sorted(extra)}"
    )


def test_documented_constants_match_the_code():
    """Token lifetimes and rate limits quoted in the doc must be real."""
    from app.core.config import settings
    from app.services.biometric_service import CHALLENGE_TTL_SECONDS, MAX_FAILED_ATTEMPTS

    doc = DOC.read_text()

    checks = [
        (f"**{settings.ACCESS_TOKEN_TTL_MINUTES} minutes**", "access token lifetime"),
        (f"**{settings.REFRESH_TOKEN_TTL_DAYS} days**", "refresh token lifetime"),
        (f'"expires_in": {settings.ACCESS_TOKEN_TTL_MINUTES * 60}', "expires_in example"),
        (f"**{settings.OTP_LENGTH}-digit**", "OTP length"),
        (f"**{settings.OTP_TTL_SECONDS // 60} minutes**", "OTP expiry"),
        (f"within {settings.OTP_RESEND_COOLDOWN_SECONDS}s", "resend cooldown"),
        (f"{settings.OTP_MAX_ATTEMPTS} wrong guesses", "per-code attempt cap"),
        (f"{settings.OTP_VERIFY_MAX_PER_HOUR} guesses in an hour", "hourly guess cap"),
        (f"{settings.LOGIN_MAX_ATTEMPTS} failures", "login attempt cap"),
        (f"{settings.LOGIN_WINDOW_SECONDS // 60} min", "login window"),
        (f"**{settings.TEMP_2FA_TOKEN_TTL_MINUTES} minutes**", "temp 2FA token life"),
        (f">{CHALLENGE_TTL_SECONDS // 60} min", "biometric challenge TTL"),
        (f"{MAX_FAILED_ATTEMPTS} consecutive failures", "biometric lockout"),
    ]

    stale = [what for needle, what in checks if needle not in doc]
    assert not stale, (
        "docs/AUTH-API.md quotes values that no longer match the code: "
        f"{stale}. Update the doc (or the config) so the two agree."
    )


def test_vendor_doc_constants_match_the_code():
    """Limits quoted in the vendor doc must be real."""
    from app.core.config import settings

    doc = VENDOR_DOC.read_text()

    checks = [
        (f"**{settings.VENDOR_AUTO_DECLINE_SECONDS} seconds**", "auto-decline window"),
        (f"{settings.HANDOFF_MAX_ATTEMPTS} incorrect", "handoff attempt cap"),
        (f"**{settings.RIDER_PIN_LENGTH}-digit**", "rider PIN length"),
        (f"{settings.MAX_PAGE_LIMIT}", "max page limit"),
        (f"{settings.PRESIGNED_URL_TTL_SECONDS // 60} minutes", "presigned URL lifetime"),
    ]

    stale = [what for needle, what in checks if needle not in doc]
    assert not stale, (
        "docs/VENDOR-API.md quotes values that no longer match the code: "
        f"{stale}. Update the doc (or the config) so the two agree."
    )


def test_vendor_doc_covers_the_flows_the_product_needs():
    """Structural guard for the vendor doc."""
    doc = VENDOR_DOC.read_text()
    for heading in (
        "## 2. Getting approved",
        "## 3. Storefront",
        "## 4. Menu",
        "## 5. Order queue",
        "## 6. The order lifecycle",
        "## 7. Handoff",
        "## 8. Analytics",
        "## 9. Images",
        "## 10. Endpoint summary",
        "## Known limitations",
    ):
        assert heading in doc, f"docs/VENDOR-API.md lost its `{heading}` section"


def test_doc_covers_the_flows_the_product_needs():
    """Structural guard — a section silently disappearing is easy to miss."""
    doc = DOC.read_text()
    for heading in (
        "## 2. Registration",
        "## 3. Login",
        "## 4. Forgot password",
        "## 5. Session management",
        "## 8. Biometric setup",
        "## 11. Vendor registration",
        "## 12. Roles",
        "## Known limitations",
    ):
        assert heading in doc, f"docs/AUTH-API.md lost its `{heading}` section"
