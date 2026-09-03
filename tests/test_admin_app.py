"""The admin console is static files served by the API at /admin.

No database is needed: these run the ASGI app without its lifespan, which is
exactly what serving a static file requires.
"""

from starlette.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    # No `with` block: skipping the lifespan keeps Postgres and Redis out of it.
    return TestClient(app)


def test_admin_console_is_served_with_a_script_friendly_csp():
    r = _client().get("/admin/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'src="admin.js"' in r.text
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp  # the console calls /api/v1 on the same origin
    assert "frame-ancestors 'none'" in csp


def test_admin_console_assets_resolve():
    c = _client()
    assert c.get("/admin/admin.js").status_code == 200
    assert c.get("/admin/admin.css").status_code == 200


def test_admin_console_has_no_inline_script():
    """The CSP has no 'unsafe-inline'; an inline <script> would silently not run."""
    html = _client().get("/admin/").text
    assert "<script>" not in html and "onclick=" not in html


def test_api_keeps_the_strict_csp():
    r = _client().get("/health")
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_admin_subdomain_serves_the_console_at_root(monkeypatch):
    """With ADMIN_UI_HOST set, requests on that host land on the console at `/`
    while API and health paths pass through untouched."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_UI_HOST", "admin.example.test")
    c = _client()
    on_admin = {"host": "admin.example.test"}

    root = c.get("/", headers=on_admin)
    assert root.status_code == 200
    assert 'src="admin.js"' in root.text
    assert "default-src 'self'" in root.headers["content-security-policy"]
    assert c.get("/admin.js", headers=on_admin).status_code == 200

    health = c.get("/health", headers=on_admin)
    assert health.status_code == 200 and health.json()["success"] is True
    assert health.headers["content-security-policy"].startswith("default-src 'none'")


def test_api_host_is_not_rewritten(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_UI_HOST", "admin.example.test")
    c = _client()
    assert c.get("/", headers={"host": "api.example.test"}).status_code == 404
    assert c.get("/admin/", headers={"host": "api.example.test"}).status_code == 200


def test_host_header_port_is_ignored(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_UI_HOST", "admin.example.test")
    r = _client().get("/", headers={"host": "Admin.Example.Test:8443"})
    assert r.status_code == 200 and 'src="admin.js"' in r.text


def test_hidden_attribute_wins_over_author_display_rules():
    """`label { display: block }` would otherwise reveal the hidden 2FA row."""
    css = _client().get("/admin/admin.css").text
    assert "[hidden] { display: none !important; }" in css


def test_console_files_are_always_revalidated():
    c = _client()
    for path in ("/admin/", "/admin/admin.js", "/admin/admin.css"):
        assert c.get(path).headers["cache-control"] == "no-cache", path
