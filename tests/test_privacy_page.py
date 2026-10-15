"""The public privacy policy served at /privacy.

Google's OAuth consent screen will not publish without a privacy policy URL on
an authorized domain, so this page is what lets Sign in with Google leave
"Testing". Like the admin console tests, no database is needed.
"""

from starlette.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    # No `with` block: skipping the lifespan keeps Postgres and Redis out of it.
    return TestClient(app)


def test_privacy_policy_is_served_without_a_redirect():
    # Google fetches the exact URL registered on the consent screen; a slash
    # redirect behind a TLS-terminating proxy can come back as http://.
    r = _client().get("/privacy", follow_redirects=False)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<h1>Privacy Policy</h1>" in r.text


def test_privacy_policy_carries_the_google_limited_use_disclosure():
    # Collapse whitespace: the HTML source wraps prose, which a browser renders
    # as single spaces.
    html = " ".join(_client().get("/privacy").text.split())
    assert "Google API Services User Data Policy" in html
    assert "Limited Use" in html
    assert "support@cheeringshop.online" in html


def test_privacy_policy_csp_allows_inline_style_but_no_script():
    r = _client().get("/privacy")
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "style-src 'unsafe-inline'" in csp
    assert "script-src" not in csp
    assert "frame-ancestors 'none'" in csp
    assert "<script" not in r.text


def test_privacy_policy_is_not_in_the_api_schema():
    assert "/privacy" not in app.openapi()["paths"]


def test_account_deletion_page_is_served_with_the_legal_page_csp():
    # The Play Console's "Data deletion" URL. Google requires it to name the
    # app, give the steps, and say what is deleted and what is kept.
    r = _client().get("/account/delete", follow_redirects=False)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == (
        "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    )
    assert "<script" not in r.text
    html = " ".join(r.text.split())
    assert "Delete your Cheering Shop account" in html
    assert "support@cheeringshop.online" in html
    assert "What is deleted" in html and "What is kept" in html
    assert "/account/delete" not in app.openapi()["paths"]


def test_privacy_policy_links_to_the_account_deletion_page():
    assert 'href="/account/delete"' in _client().get("/privacy").text
